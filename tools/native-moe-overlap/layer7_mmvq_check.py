"""Conditional CUDA MMVQ edge checks; vendor math accuracy is an assumption."""
from decimal import Decimal, localcontext
import ctypes
import math
import struct

PROFILE = 'b29c606e-q8_0-mmvq-vendor-accuracy-union/1'
ASSUMPTION = ('CUDA division is RN or within the documented 2-ULP approximate envelope; '
              'expf obeys the ordinary/fast documented accuracy envelope; those math '
              'tables are vendor-tested limits, not guaranteed bounds. No observed '
              'nvcc flag, historical device byte or numerical qualification is asserted.')


class Unknown(ValueError):
    pass


def f32(x):
    y = struct.unpack('<f', struct.pack('<f', x))[0]
    if not math.isfinite(y):
        raise ValueError('nonfinite F32 operation')
    if y and abs(y) < 2**-126:
        raise Unknown('F32 underflow/FTZ outside conditional profile')
    return y


def step(x, n):
    """Adjacent F32 values. Four neighbours cover 2 ULP across binades."""
    if x == 0:
        return struct.unpack('<f', struct.pack('<I', n if n >= 0 else 0x80000000-n))[0]
    bits = struct.unpack('<I', struct.pack('<f', x))[0]
    return struct.unpack('<f', struct.pack('<I', bits+(n if x > 0 else -n)))[0]


def quantization_bounds(values):
    if not values or len(values) % 32 or not all(math.isfinite(v) for v in values):
        raise ValueError('finite complete Q8 operand required')
    low, high, ambiguous = bytearray(), bytearray(), 0
    for at in range(0, len(values), 32):
        xs = values[at:at+32]; amax = max(map(abs, xs))
        if amax == 0:
            low.extend(bytes(34)); high.extend(bytes(34)); continue
        if amax > 1024 or any(x and abs(x) < 2**-126 for x in xs):
            raise Unknown('activation range/FTZ outside conditional profile')
        d = f32(amax/127); dl, dh = step(d, -4), step(d, 4)
        hl, hh = struct.pack('<e', dl), struct.pack('<e', dh)
        if struct.unpack('<e', hl)[0] <= 0:
            raise Unknown('activation F16 scale underflow')
        low.extend(hl); high.extend(hh)
        for x in xs:
            qs = sorted((f32(x/dl), f32(x/dh)))
            l, h = step(qs[0], -4), step(qs[1], 4)
            away = lambda v: math.floor(v+.5) if v >= 0 else math.ceil(v-.5)
            ql, qh = away(l), away(h)
            if not -127 <= ql <= qh <= 127:
                raise Unknown('quantized integer range unsupported')
            low.extend(struct.pack('<b', ql)); high.extend(struct.pack('<b', qh))
            ambiguous += ql != qh
    return bytes(low), bytes(high), ambiguous


def compare_bounds(bounds, observed):
    if not bounds or len(bounds) != len(observed):
        raise ValueError('matching nonempty bounded outputs required')
    if not all(math.isfinite(x) for pair in bounds for x in pair) or not all(math.isfinite(x) for x in observed):
        raise ValueError('nonfinite bounds/output')
    if any(l > h for l, h in bounds):
        raise ValueError('reversed interval')
    outside = [i for i, ((l, h), x) in enumerate(zip(bounds, observed)) if not l <= x <= h]
    return dict(status='mismatch' if outside else 'match', coordinates=len(observed),
                outside=len(outside), first_outside=outside[0] if outside else None,
                max_interval_width=max(h-l for l, h in bounds))


def projection(helper, bank, operands, observed, mapping, width, rows, tokens, down=False):
    if tokens not in (1, 2, 4, 8):
        return dict(status='unknown', reason='MMQ/unsupported width has no profile')
    if not (32 <= width <= 2560 and width % 32 == 0 and 1 <= rows <= 2560):
        return dict(status='unknown', reason='unsupported MMVQ dimensions')
    if len(bank) != 5*rows*(width//32*34) or len(observed) != tokens*5*rows:
        raise ValueError('MMVQ bank/output shape mismatch')
    if len(operands) != tokens*(5 if down else 1)*width:
        raise ValueError('MMVQ input shape mismatch')
    if not all(math.isfinite(x) for x in (*operands, *observed)):
        raise ValueError('nonfinite MMVQ operand/result')
    if not all(math.isfinite(struct.unpack_from('<e', bank, at)[0]) for at in range(0, len(bank), 34)):
        raise ValueError('nonfinite MMVQ bank scale')
    fun = helper.library.l7_dot_bounds
    fun.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    all_bounds = [None]*len(observed); controls = []; ambiguous = 0
    try:
        quantized = {}
        for e in mapping:
            if e['branch'] != 'hot': continue
            t, slot, expert = e['token'], e['branch_slot'], e['compact_expert']
            key = t*5+slot if down else t
            if key not in quantized:
                quantized[key] = quantization_bounds(operands[key*width:(key+1)*width])
                ambiguous += quantized[key][2]
            ql, qh, _ = quantized[key]; block = []
            for c in range(rows):
                at = (expert*rows+c)*(width//32*34); out = (ctypes.c_double*2)()
                fun(bank[at:at+width//32*34], ql, qh, width, out)
                bound = (out[0], out[1]); all_bounds[(t*5+slot)*rows+c] = bound; block.append(bound)
            controls.append(dict(token=t, expert=e['global_expert'],
                status='rejected' if any(not l <= 0 <= h for l, h in block) else 'insensitive'))
    except Unknown as error:
        return dict(status='unknown', reason=str(error))
    if any(b is None for b in all_bounds):
        raise ValueError('MMVQ mapping coverage mismatch')
    result = compare_bounds(all_bounds, observed)
    result.update(ambiguous_bytes=ambiguous, zero_expert_controls=controls,
                  sensitive=all(c['status'] == 'rejected' for c in controls))
    return result


def swiglu_bounds(gate, up):
    if len(gate) != len(up) or not gate:
        raise ValueError('SwiGLU matching shapes required')
    bounds = []
    for g, u in zip(gate, up):
        if not math.isfinite(g) or not math.isfinite(u):
            raise ValueError('nonfinite SwiGLU')
        if abs(g) > 16:
            raise Unknown('SwiGLU |gate|>16 outside profile')
        if g == 0 or u == 0:
            bounds.append((0., 0.)); continue
        # Decimal.exp is correctly rounded at the selected precision. An extra
        # neighbour covers conversion to the F32 reference. This envelope covers
        # ordinary expf and both published 1.16/1.173 fast-exponential factors.
        with localcontext() as context:
            context.prec = 80
            center = f32(float((-Decimal.from_float(g)).exp()))
        error = 4+math.ceil(2*abs(g))
        el, eh = step(center, -error), step(center, error)
        denominators = (f32(1+el), f32(1+eh))
        q = sorted(f32(g/d) for d in denominators)
        lo, hi = step(q[0], -4), step(q[1], 4)
        products = sorted((f32(lo*u), f32(hi*u)))
        bounds.append((products[0], products[1]))
    return bounds


def swiglu(gate, up, observed, rows, tokens):
    if len(observed) != tokens*5*rows:
        raise ValueError('SwiGLU output shape mismatch')
    try:
        bounds = swiglu_bounds(gate, up)
    except Unknown as error:
        return dict(status='unknown', reason=str(error))
    result = compare_bounds(bounds, observed)
    result['sensitive'] = all(any(not l <= 0 <= h for l, h in bounds[at:at+rows])
                              for at in range(0, len(bounds), rows))
    return result
