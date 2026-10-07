"""Check that public bundles reject runtime secrets, unsafe archives and tampering."""
import hashlib,io,json,tarfile,tempfile,unittest
from pathlib import Path
from export_infra_bundle import export_bundle


class InfrastructureExport(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.out=self.root/'docs'
        (self.source/'deliverables').mkdir(parents=True);(self.out/'data').mkdir(parents=True)

    def archive(self,files=None,symlink=False,completion=None,complete=False):
        files=files or {'unit_templates/runtime.env.example':b'CODEX_HOME=/authorized/existing/home\n'}
        manifest=dict(active_methods=['gpt_only','pi05_plus_gpt'],full_reproduction_complete=False,
            created_utc='2026-10-02T00:00:00Z',files=[dict(path=k,size=len(v),sha256=hashlib.sha256(v).hexdigest()) for k,v in files.items()])
        manifest['full_reproduction_complete']=complete
        if completion:manifest['completion_certificate']=completion
        path=self.source/'deliverables/infrastructure_bundle_20261002.tar.gz'
        with tarfile.open(path,'w:gz') as tar:
            for name,data in {**files,'manifest.json':json.dumps(manifest).encode()}.items():
                info=tarfile.TarInfo(name);info.size=len(data)
                if symlink and name!='manifest.json':info.type=tarfile.SYMTYPE;info.linkname='/tmp/private';info.size=0
                tar.addfile(info,io.BytesIO(data) if info.isfile() else None)
        receipt=dict(path=str(path.relative_to(self.source)),bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),files=len(files),contents_verified=True)
        (self.source/'deliverables/infrastructure_bundle_verification.json').write_text(json.dumps(receipt))
        return path

    def test_verified_bundle_exports_unchanged_bytes_and_explicit_partial_status(self):
        path=self.archive();value=export_bundle(self.source,self.out)
        self.assertEqual((self.out/value['archive']).read_bytes(),path.read_bytes())
        self.assertFalse(value['full_reproduction_complete'])
        self.assertEqual(value['active_methods'],['gpt_only','pi05_plus_gpt'])

    def test_rejects_tampered_archive_before_copy(self):
        path=self.archive();path.write_bytes(path.read_bytes()+b'tampered')
        with self.assertRaises(AssertionError):export_bundle(self.source,self.out)
        self.assertFalse((self.out/'downloads').exists())

    def test_rejects_private_runtime_artifacts_even_with_valid_receipt(self):
        for name in ('auth.json','rpc_out.jsonl','private/runtime_db/state.db'):
            with self.subTest(name=name):
                self.archive({name:b'private'})
                with self.assertRaises(AssertionError):export_bundle(self.source,self.out)

    def test_rejects_secret_content_even_inside_documentation(self):
        self.archive({'RUNBOOK.md':b'ghp_'+b'a'*40})
        with self.assertRaises(AssertionError):export_bundle(self.source,self.out)

    def test_rejects_path_traversal_and_symlinks(self):
        for name,symlink in (('../escape.py',False),('/absolute.py',False),('link.py',True)):
            with self.subTest(name=name):
                self.archive({name:b'print(1)'},symlink=symlink)
                with self.assertRaises(AssertionError):export_bundle(self.source,self.out)

    def completion_proof(self):
        rows=[dict(cohort=c,case_id=str(i),method=m,run_id=c+str(i)+m,audit_inputs=1,
                   audit_sha256='a'*64,original_video_sha256='b'*64)
              for c in ('robodojo','robolab') for i in range(50) for m in ('gpt_only','pi05_plus_gpt')]
        return dict(schema='gpt_policy_full_reproduction_gate.v1',status='complete',full_reproduction_complete=True,
                    original_artifacts_verified=True,public_episode_artifacts_verified=True,
                    published_commit='c'*40,verified_native_episodes=200,active=None,
                    cohorts={c:dict(complete_method_runs=100,completed_pairs=50,remaining_method_runs=0,remaining_pairs=0)
                             for c in ('robodojo','robolab')},original_episodes=rows,
                    retained_original_episodes=[dict(rows[0])],original_robodojo=dict(complete_method_runs=99),
                    public_files=[dict(path='data/'+str(i),sha256='d'*64,bytes=1) for i in range(815)],
                    exact_commit_ci=[dict(conclusion='success')],finished_utc='2026-10-07T09:34:13Z',
                    limitation='Historical source and complete initial physics states unavailable.')

    def completion_archive(self,proof,binding_sha=None):
        data=json.dumps(proof).encode();name='sealed/certificate.json'
        binding=dict(path=name,sha256=binding_sha or hashlib.sha256(data).hexdigest(),published_commit='c'*40)
        self.archive({name:data},complete=True,completion=binding)
        return data

    def test_completed_snapshot_exports_exact_sealed_receipt_and_qualified_commit(self):
        data=self.completion_archive(self.completion_proof());value=export_bundle(self.source,self.out)
        self.assertTrue(value['full_reproduction_complete'])
        self.assertEqual(value['completion_certificate']['published_commit'],'c'*40)
        self.assertEqual((self.out/value['completion_certificate']['public_path']).read_bytes(),data)

    def test_completion_claim_requires_certificate(self):
        self.archive(complete=True)
        with self.assertRaises(AssertionError):export_bundle(self.source,self.out)

    def test_rejects_certificate_with_valid_bundle_hash_but_invalid_binding(self):
        self.completion_archive(self.completion_proof(),binding_sha='e'*64)
        with self.assertRaises(AssertionError):export_bundle(self.source,self.out)

    def test_rejects_incomplete_duplicate_or_unverified_completion_evidence(self):
        def incomplete(p):p['cohorts']['robolab']['complete_method_runs']=99
        def duplicate(p):p['original_episodes'][1]=p['original_episodes'][0]
        def pending_ci(p):p['exact_commit_ci'][0]['conclusion']='failure'
        def wrong_commit(p):p['published_commit']='e'*40
        def unverified(p):p['original_artifacts_verified']=False
        for mutation in (incomplete,duplicate,pending_ci,wrong_commit,unverified):
            with self.subTest(mutation=mutation.__name__):
                proof=self.completion_proof();mutation(proof);self.completion_archive(proof)
                with self.assertRaises(AssertionError):export_bundle(self.source,self.out)


if __name__=='__main__':unittest.main()
