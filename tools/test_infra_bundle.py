"""Check that public bundles reject runtime secrets, unsafe archives and tampering."""
import hashlib,io,json,tarfile,tempfile,unittest
from pathlib import Path
from export_infra_bundle import export_bundle


class InfrastructureExport(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.out=self.root/'docs'
        (self.source/'deliverables').mkdir(parents=True);(self.out/'data').mkdir(parents=True)

    def archive(self,files=None,symlink=False):
        files=files or {'unit_templates/runtime.env.example':b'CODEX_HOME=/authorized/existing/home\n'}
        manifest=dict(active_methods=['gpt_only','pi05_plus_gpt'],full_reproduction_complete=False,
            created_utc='2026-10-02T00:00:00Z',files=[dict(path=k,size=len(v),sha256=hashlib.sha256(v).hexdigest()) for k,v in files.items()])
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


if __name__=='__main__':unittest.main()
