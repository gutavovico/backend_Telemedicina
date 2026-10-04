"""Claves de storage: se rechazan rutas/URLs absolutas (anti doble-ruta /file//api/...)."""
import unittest

from app.modules.medical_records.clinical_documents.storage import StorageError, _sanitize_key


class StorageKeyTestCase(unittest.TestCase):
    def test_claves_relativas_validas(self):
        self.assertEqual(_sanitize_key("seed/a.pdf"), "seed/a.pdf")
        self.assertEqual(_sanitize_key("/seed/a.pdf"), "seed/a.pdf")
        self.assertEqual(_sanitize_key("documentos/ab/cd/f.pdf"), "documentos/ab/cd/f.pdf")

    def test_rutas_absolutas_rechazadas(self):
        for mala in (
            "",
            "   ",
            "/api/v1/documentos/download/x.pdf",
            "api/x.pdf",
            "http://evil/a.pdf",
            "https://evil/a.pdf",
            "..\\a.pdf",
            "sub\\dir\\a.pdf",
        ):
            with self.subTest(clave=mala):
                with self.assertRaises(StorageError):
                    _sanitize_key(mala)


if __name__ == "__main__":
    unittest.main()
