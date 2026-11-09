"""Classificação e resumo dos testes de qualidade a partir dos artefatos do dbt."""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'relatorio', Path(__file__).resolve().parents[2] / 'scripts/quality/relatorio_qualidade.py')
relatorio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relatorio)


def generico(nome, teste, modelo, **kwargs):
    return {f'test.mandato_aberto.{nome}': {
        'name': nome, 'tags': [], 'attached_node': f'model.mandato_aberto.{modelo}',
        'test_metadata': {'name': teste, 'kwargs': kwargs}}}


def singular(nome, tags, depende):
    return {f'test.mandato_aberto.{nome}': {
        'name': nome, 'tags': tags, 'depends_on': {'nodes': [depende]}}}


def manifest():
    nos = {}
    nos |= generico('esq', 'esquema_esperado', 'fct_despesas', colunas={'valor': 'decimal'})
    nos |= generico('vol', 'volume_minimo', 'fct_despesas', minimo='despesas_min')
    nos |= generico('uni', 'unique', 'dim_senador', column_name='senador_id')
    nos |= generico('rel', 'relationships', 'fct_despesas', column_name='senador_id')
    nos |= generico('regra', 'regra_linha', 'fct_registros_presenca', expressao='a  =\n b')
    nos |= generico('prop', 'proporcao', 'fct_despesas', condicao='valor = 0')
    nos |= singular('hist', ['qualidade', 'historico'], 'model.mandato_aberto.dim_fornecedor_historico')
    nos |= singular('rec', ['qualidade', 'integridade'], 'source.mandato_aberto.oltp.despesas')
    nos |= singular('sem_dimensao', [], 'model.mandato_aberto.x')
    nos['model.mandato_aberto.fct_despesas'] = {'name': 'fct_despesas'}
    return {'nodes': nos}


def resultados(**status):
    padrao = {'esq': 'pass', 'vol': 'pass', 'uni': 'pass', 'rel': 'pass', 'regra': 'pass',
              'prop': 'pass', 'hist': 'pass', 'rec': 'pass', 'sem_dimensao': 'pass'}
    padrao |= status
    linhas = [{'unique_id': f'test.mandato_aberto.{n}', 'status': s,
               'failures': 0 if s == 'pass' else 3, 'message': 'linha 1\nlinha 2'}
              for n, s in padrao.items()]
    linhas.append({'unique_id': 'model.mandato_aberto.fct_despesas', 'status': 'success'})
    return {'metadata': {'generated_at': '2026-11-08T12:00:00Z'}, 'args': {'which': 'build'},
            'results': linhas}


class RelatorioQualidade(unittest.TestCase):
    def test_classifica_as_seis_dimensoes(self):
        resumo = relatorio.resumir(manifest(), resultados())
        totais = {d: c['total'] for d, c in resumo['dimensoes'].items()}
        self.assertEqual(totais, {'esquema': 1, 'volume': 1, 'unicidade': 1, 'integridade': 3,
                                  'historico': 1, 'distribuicao': 1, 'outros': 1})
        self.assertTrue(resumo['aprovado'])
        self.assertEqual(resumo['executado_em'], '2026-11-08T12:00:00Z')

    def test_modelos_nao_entram_na_contagem(self):
        resumo = relatorio.resumir(manifest(), resultados())
        self.assertEqual(sum(c['total'] for c in resumo['dimensoes'].values()), 9)

    def test_aviso_nao_reprova_e_falha_reprova(self):
        self.assertTrue(relatorio.resumir(manifest(), resultados(prop='warn'))['aprovado'])
        self.assertFalse(relatorio.resumir(manifest(), resultados(hist='fail'))['aprovado'])
        self.assertFalse(relatorio.resumir(manifest(), resultados(esq='error'))['aprovado'])

    def test_problemas_ordenados_e_rotulados(self):
        resumo = relatorio.resumir(manifest(), resultados(prop='warn', hist='fail', rel='error',
                                                           regra='fail'))
        self.assertEqual([p['status'] for p in resumo['problemas']], ['error', 'fail', 'fail', 'warn'])
        primeiro, regra = resumo['problemas'][0], resumo['problemas'][1]
        self.assertEqual(primeiro['teste'], 'relationships(senador_id)')
        self.assertEqual(primeiro['mensagem'], 'linha 1')
        self.assertEqual(regra['teste'], 'regra_linha(a = b)')
        self.assertEqual(regra['alvo'], 'fct_registros_presenca')

    def test_alvo_de_fonte_e_rotulo_de_esquema(self):
        resumo = relatorio.resumir(manifest(), resultados(rec='fail', esq='fail'))
        por_teste = {p['teste']: p for p in resumo['problemas']}
        self.assertEqual(por_teste['rec']['alvo'], 'oltp.despesas')
        self.assertIn('esquema_esperado', por_teste)

    def test_main_grava_json_e_devolve_codigo(self):
        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta)
            (alvo / 'manifest.json').write_text(json.dumps(manifest()), encoding='utf-8')
            (alvo / 'run_results.json').write_text(json.dumps(resultados(vol='fail')), encoding='utf-8')
            saida = alvo / 'resumo.json'
            with redirect_stdout(io.StringIO()) as texto:
                codigo = relatorio.main(['--target', str(alvo), '--json', str(saida)])
            self.assertEqual(codigo, 1)
            self.assertIn('REPROVADA', texto.getvalue())
            self.assertEqual(json.loads(saida.read_text(encoding='utf-8'))['dimensoes']['volume']['fail'], 1)

    def test_main_sem_artefatos(self):
        with tempfile.TemporaryDirectory() as pasta, redirect_stderr(io.StringIO()):
            self.assertEqual(relatorio.main(['--target', pasta]), 2)


if __name__ == '__main__':
    unittest.main()
