"""Opaque budget primitives with explicitly SYNTHETIC profile evidence."""
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import unittest
from inferswarm.operator.config import parse_config, profile_subject
from tests.issue299_fixture import NOW, synthetic_config


class AdmissionContracts(unittest.TestCase):
    def api(self):
        from inferswarm.operator import plan
        for name in ('ResourceCharge','LegalCandidate','admit_candidate'):
            self.assertTrue(hasattr(plan,name),f'missing admission API: {name}')
        return plan

    def setup_case(self,charges=()):
        api=self.api(); config=parse_config(synthetic_config(),now=NOW,profile_mode='replay')
        candidate=api.LegalCandidate('opaque',(),(),(),tuple(charges),(),(),
            subject=profile_subject(config,profile_mode='replay'), required_charge_ids=tuple(sorted(c.allocation_id for c in charges)),
            calculated_evidence=('source:synthetic-test',))
        return api,config,candidate

    def charge(self,allocation='x',amount=100,memory='A-ram',phase='serve',role='required',shared=None):
        return self.api().ResourceCharge(allocation,memory,role,amount,phase,'source:synthetic-test',shared)

    def test_api_required_then_known_charge(self):
        p,c,candidate=self.setup_case([self.charge()])
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
        self.assertEqual(receipt.status,'ADMITTED')
        self.assertFalse(receipt.execution_ready)  # Replay is not live authority.
        self.assertEqual(next(r for r in receipt.peaks if r.memory_id=='A-ram').peak_bytes,100)
        self.assertEqual(next(r for r in receipt.peaks if r.memory_id=='A-ram').existing_load_bytes,100000)

    def test_unknown_and_omitted_required_charges_never_zero(self):
        for allocation in ('repacking','workspace','graph','staging','observer','mmap-resident','cache-vector'):
            with self.subTest(allocation=allocation):
                charge=self.charge(allocation,amount=None)
                p,c,candidate=self.setup_case([charge])
                receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
                self.assertEqual(receipt.status,'BLOCKED')
                self.assertTrue(any('UNKNOWN' in r and allocation in r for r in receipt.deficits))
                receipt=p.admit_candidate(replace(candidate,charges=()),c.profiles.snapshot,c.policy,now=NOW)
                self.assertTrue(any('missing required allocation' in r and allocation in r for r in receipt.deficits))

    def test_shared_allocation_only_dedupes_proven_equal_alias(self):
        a=self.charge('CPU-bookkeeping',amount=450000,shared='shared-physical')
        b=self.charge('GPU-host-bookkeeping',amount=450000,shared='shared-physical')
        p,c,candidate=self.setup_case([a,b])
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
        self.assertEqual(receipt.status,'ADMITTED')
        peak=next(r for r in receipt.peaks if r.memory_id=='A-ram')
        self.assertEqual(peak.peak_bytes,450000)
        for bad in (replace(b,bytes=450001),replace(b,phase='load'),replace(b,role='optional'),
                    replace(b,memory_id='B-ram'),replace(b,evidence_id='unknown:other')):
            with self.subTest(bad=bad):
                receipt=p.admit_candidate(replace(candidate,charges=(a,bad)),c.profiles.snapshot,c.policy,now=NOW)
                self.assertTrue(any('inconsistent shared alias' in r for r in receipt.deficits))
        distinct=replace(candidate,charges=(replace(a,shared_allocation_id=None),replace(b,shared_allocation_id=None)))
        receipt=p.admit_candidate(distinct,c.profiles.snapshot,c.policy,now=NOW)
        self.assertEqual(next(r for r in receipt.peaks if r.memory_id=='A-ram').peak_bytes,900000)
        self.assertEqual(receipt.status,'BLOCKED')

    def test_phase_peaks_simultaneous_and_distinct_mirrors(self):
        charges=[self.charge('load',amount=500000,phase='load'),self.charge('serve',amount=600000),
                 self.charge('mirror',amount=100000,role='optional')]
        p,c,candidate=self.setup_case(charges)
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
        peak=next(r for r in receipt.peaks if r.memory_id=='A-ram')
        self.assertEqual(peak.peak_bytes,700000)
        self.assertEqual(dict(peak.phase_bytes)['load'],500000)
        self.assertEqual(dict(peak.phase_bytes)['serve'],700000)
        self.assertEqual(receipt.status,'ADMITTED')
        candidate=replace(candidate,charges=candidate.charges+(self.charge('other-mirror',amount=200000,role='optional'),))
        self.assertEqual(p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW).status,'BLOCKED')

    def test_peak_reserve_and_memavailable_are_independent(self):
        p,c,candidate=self.setup_case([self.charge(amount=899999)])
        self.assertEqual(p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW).status,'ADMITTED')
        receipt=p.admit_candidate(replace(candidate,charges=(self.charge(amount=900000),)),c.profiles.snapshot,c.policy,now=NOW)
        self.assertTrue(any('projected available reserve' in r for r in receipt.deficits))
        policy=replace(c.policy,memory_limits=tuple(replace(r,peak_bytes=899998) if r.memory_id=='A-ram' else r for r in c.policy.memory_limits))
        self.assertTrue(any('policy peak' in r for r in p.admit_candidate(candidate,c.profiles.snapshot,policy,now=NOW).deficits))
        policy=replace(c.policy,memory_limits=tuple(replace(r,min_available_bytes=900001) if r.memory_id=='A-ram' else r for r in c.policy.memory_limits))
        self.assertTrue(any('MemAvailable' in r for r in p.admit_candidate(candidate,c.profiles.snapshot,policy,now=NOW).deficits))

    def test_virtual_is_separate_not_residency_proof(self):
        charges=[self.charge('mmap-virtual',amount=188225033248,role='virtual'),self.charge('mmap-resident',amount=None)]
        p,c,candidate=self.setup_case(charges)
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
        self.assertEqual(receipt.status,'BLOCKED')
        peak=next(r for r in receipt.peaks if r.memory_id=='A-ram')
        self.assertEqual(peak.virtual_bytes,188225033248)
        self.assertTrue(any('UNKNOWN' in r and 'mmap-resident' in r for r in receipt.deficits))

    def test_freshness_missing_evidence_and_duplicate_physical_capacity(self):
        p,c,candidate=self.setup_case([self.charge()])
        self.assertTrue(any('expired evidence' in r for r in p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW+timedelta(hours=2)).deficits))
        receipt=p.admit_candidate(replace(candidate,charges=(replace(candidate.charges[0],evidence_id='nonexistent'),)),c.profiles.snapshot,c.policy,now=NOW)
        self.assertTrue(any('missing charge evidence' in r for r in receipt.deficits))
        snapshot=replace(c.profiles.snapshot,memory_resources=c.profiles.snapshot.memory_resources+(c.profiles.snapshot.memory_resources[0],))
        with self.assertRaisesRegex(ValueError,'duplicate memory_id'): p.admit_candidate(candidate,snapshot,c.policy,now=NOW)

    def test_policy_failure_does_not_masquerade_as_unknown_technical_fit(self):
        p,c,candidate=self.setup_case([self.charge(amount=100)])
        policy=replace(c.policy,memory_limits=tuple(replace(r,peak_bytes=99) if r.memory_id=='A-ram' else r for r in c.policy.memory_limits))
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,policy,now=NOW)
        self.assertEqual(receipt.technical_feasibility,'FEASIBLE')
        self.assertFalse(receipt.policy_eligible)
        self.assertEqual(receipt.status,'BLOCKED')

    def test_candidate_rejects_mutable_opaque_payloads(self):
        p,c,candidate=self.setup_case([self.charge()])
        for field,value in [('assignments',([1],)),('charges',[self.charge()]),('source_contract',({'opaque':1},))]:
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'immutable candidate'):
                replace(candidate,**{field:value})

    def test_exact_host_and_gpu_boundaries(self):
        for mid,capacity,available in [('A-ram',1000000,900000),('B-vram',500000,400000)]:
            with self.subTest(memory=mid):
                p,c,candidate=self.setup_case([self.charge(amount=available-1,memory=mid)])
                self.assertEqual(p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW).status,'ADMITTED')
                self.assertTrue(any('projected available reserve' in r for r in p.admit_candidate(replace(candidate,charges=(self.charge(amount=available,memory=mid),)),c.profiles.snapshot,c.policy,now=NOW).deficits))
                self.assertTrue(any('physical capacity deficit' in r for r in p.admit_candidate(replace(candidate,charges=(self.charge(amount=capacity,memory=mid),)),c.profiles.snapshot,c.policy,now=NOW).deficits))

    def test_omitted_required_allocation_and_duplicate_id_are_independent(self):
        p,c,candidate=self.setup_case([self.charge('omitted')])
        receipt=p.admit_candidate(replace(candidate,charges=()),c.profiles.snapshot,c.policy,now=NOW)
        self.assertTrue(any('missing required allocation: omitted'==r for r in receipt.deficits))
        receipt=p.admit_candidate(replace(candidate,charges=candidate.charges*2),c.profiles.snapshot,c.policy,now=NOW)
        self.assertTrue(any('duplicate allocation identity'==r for r in receipt.deficits))

    def test_structural_deficits_distinct_from_unknown_budgets(self):
        p,c,candidate=self.setup_case([self.charge()])
        receipt=p.admit_candidate(replace(candidate,charges=()),c.profiles.snapshot,c.policy,now=NOW)
        self.assertFalse(receipt.structural_admissible)
        receipt=p.admit_candidate(replace(candidate,charges=candidate.charges*2),c.profiles.snapshot,c.policy,now=NOW)
        self.assertFalse(receipt.structural_admissible)
        unknown=replace(candidate,charges=(replace(candidate.charges[0],bytes=None),))
        self.assertTrue(p.admit_candidate(unknown,c.profiles.snapshot,c.policy,now=NOW).structural_admissible)

    def test_nonfinite_opaque_candidate_is_rejected(self):
        p,c,candidate=self.setup_case([self.charge()])
        for value in (float('nan'),float('inf'),float('-inf')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'immutable candidate'):
                replace(candidate,source_contract=(value,))

    def test_reserve_lifetimes_do_not_overlap_disjoint_phase_peaks(self):
        charges=(self.charge('load',amount=800000,phase='load'),
                 self.charge('serve',amount=100000),
                 self.charge('serve-headroom',amount=200000,role='reserve'))
        p,c,candidate=self.setup_case(charges)
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
        self.assertEqual(receipt.status,'ADMITTED',receipt.deficits)
        self.assertEqual(next(r for r in receipt.peaks if r.memory_id=='A-ram').reserve_bytes,200001)

    def test_estimated_runtime_claim_is_not_qualified_capability(self):
        from tests.issue299_fixture import reseal_profiles,profile_digest
        raw=synthetic_config()
        evidence=next(e for e in raw['profiles']['snapshot']['evidence'] if e['evidence_id']=='synthetic-runtime-A-cpu')
        evidence['evidence_class']='estimated'
        raw['policy']['allowed_evidence_classes'].append('estimated')
        reseal_profiles(raw['profiles']['snapshot']); raw['profiles']['digest']=profile_digest(raw['profiles']['snapshot'])
        c=parse_config(raw,now=NOW,profile_mode='replay')
        p,_,candidate=self.setup_case([self.charge()])
        candidate=replace(candidate,capability_requirements=(p.CapabilityRequirement('runtime-A-cpu','opaque-capability','opaque qualification'),))
        receipt=p.admit_candidate(candidate,c.profiles.snapshot,c.policy,now=NOW)
        self.assertEqual(receipt.status,'BLOCKED')
        self.assertTrue(any('UNKNOWN capability evidence' in reason for reason in receipt.deficits))
        self.assertIn(('synthetic-runtime-A-cpu','estimated','synthetic'),receipt.evidence_classes)

    def test_strict_charge_values_and_immutability(self):
        p,c,candidate=self.setup_case([self.charge()])
        for value in (True,-1,1.5,float('inf')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'charge bytes'): self.charge(amount=value)
        with self.assertRaisesRegex(ValueError,'charge role'): self.charge(role='guess')
        with self.assertRaisesRegex(ValueError,'charge phase'): self.charge(phase='sometimes')
        with self.assertRaises(FrozenInstanceError): candidate.charges[0].bytes=0


if __name__=='__main__': unittest.main()
