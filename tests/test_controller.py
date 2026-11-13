import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from agent import allowed_path, extract_json_object, validate_ops

class ControllerTests(unittest.TestCase):
    def test_json_extraction(self):
        self.assertEqual(extract_json_object('```json\n{"files": []}\n```'), {'files': []})

    def test_rejects_sensitive_paths(self):
        for p in ['.github/workflows/ci.yml', '.env', '../x', 'agent.py', 'tests/../../bad']:
            self.assertFalse(allowed_path(p))

    def test_accepts_app_and_tests(self):
        self.assertTrue(allowed_path('app/main.py'))
        self.assertTrue(allowed_path('tests/test_main.py'))

    def test_operations_validation(self):
        with TemporaryDirectory() as d:
            self.assertEqual(len(validate_ops({'files':[{'path':'app/a.py','content':'print(1)'}]}, Path(d))),1)
            with self.assertRaises(ValueError):
                validate_ops({'files':[{'path':'.github/workflows/ci.yml','content':'bad'}]},Path(d))

if __name__ == '__main__':
    unittest.main()
