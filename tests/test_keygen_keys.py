import unittest

from tests._tmpdir import make_temp_dir, remove_temp_dir
from continuum.keys import write_keypair_ed25519


class KeygenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("keys")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def test_write_keypair_ed25519_creates_files(self) -> None:
        priv_path, pub_path = write_keypair_ed25519(self.root)
        self.assertTrue(priv_path.is_file())
        self.assertTrue(pub_path.is_file())
        priv = priv_path.read_text(encoding="utf-8").strip()
        pub = pub_path.read_text(encoding="utf-8").strip()
        self.assertGreater(len(priv), 20)
        self.assertGreater(len(pub), 20)
        self.assertEqual(priv_path.name, "continuum_private.key")
        self.assertEqual(pub_path.name, "continuum_public.key")


if __name__ == "__main__":
    unittest.main()
