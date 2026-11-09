"""Cenários temporais do contexto oficial, sem chamadas HTTP."""
import copy
import importlib.util
from pathlib import Path
import unittest
import tempfile
import stat

spec = importlib.util.spec_from_file_location('contexto', Path(__file__).resolve().parents[2] / 'scripts/modeling/atualizar_contexto.py')
contexto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contexto)


def payload():
    return {'MandatoParlamentar': {'Parlamentar': {'Codigo': '1', 'Mandatos': {'Mandato': {
        'UfParlamentar': 'DF',
        'PrimeiraLegislaturaDoMandato': {'DataInicio': '2023-02-01', 'DataFim': '2027-01-31'},
        'Exercicios': {'Exercicio': {'DataInicio': '2024-01-15', 'DataFim': '2024-02-10'}},
        'Partidos': {'Partido': {'Sigla': 'A', 'DataFiliacao': '2023-01-01'}}
    }}}}}


class ContextTests(unittest.TestCase):
    def test_partial_month_and_no_exercise(self):
        rows = contexto.monthly_context(payload(), 1, 2024)
        self.assertEqual(rows[0]['dias_exercicio'], 17)
        self.assertEqual(rows[1]['dias_exercicio'], 10)
        self.assertEqual(rows[0]['partido_competencia'], 'A')
        self.assertEqual(rows[2]['status_partido'], 'SEM_EXERCICIO')

    def test_party_change_inside_month(self):
        p = payload()
        p['MandatoParlamentar']['Parlamentar']['Mandatos']['Mandato']['Partidos']['Partido'] = [
            {'Sigla': 'A', 'DataFiliacao': '2023-01-01', 'DataDesfiliacao': '2024-01-20'},
            {'Sigla': 'B', 'DataFiliacao': '2024-01-21'}]
        rows = contexto.monthly_context(p, 1, 2024)
        self.assertEqual(rows[0]['status_partido'], 'MULTIPLOS')
        self.assertEqual(rows[0]['partido_competencia'], '')
        self.assertEqual(rows[1]['partido_competencia'], 'B')
        self.assertEqual(rows[0]['uf_competencia'], 'DF')

    def test_missing_party_coverage_is_not_current_party(self):
        p = payload()
        p['MandatoParlamentar']['Parlamentar']['Mandatos']['Mandato']['Partidos']['Partido']['DataFiliacao'] = '2024-01-20'
        self.assertEqual(contexto.monthly_context(p, 1, 2024)[0]['status_partido'], 'SEM_COBERTURA')

    def test_duplicate_exercises_do_not_double_days(self):
        p = payload()
        m = p['MandatoParlamentar']['Parlamentar']['Mandatos']['Mandato']
        p['MandatoParlamentar']['Parlamentar']['Mandatos']['Mandato'] = [m, copy.deepcopy(m)]
        self.assertEqual(contexto.monthly_context(p, 1, 2024)[0]['dias_exercicio'], 17)

    def test_seed_is_readable_by_container_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'contexto.csv'
            contexto.write_seed(target, [])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            self.assertNotIn(b'\r', target.read_bytes())

    def test_failed_write_preserves_previous_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'contexto.csv'
            target.write_text('anterior')
            with self.assertRaises(ValueError):
                contexto.write_seed(target, [{'coluna_inesperada': 'erro'}])
            self.assertEqual(target.read_text(), 'anterior')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_identity_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            contexto.monthly_context(payload(), 2, 2024)


if __name__ == '__main__':
    unittest.main()
