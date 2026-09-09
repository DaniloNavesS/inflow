import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import styles from './index.module.css';

const chapters = [
  {number: '01', title: 'Contexto e propósito', description: 'O problema, as perguntas e o recorte que orientam a análise dos gastos parlamentares.', anchor: 'sobre-o-projeto', tag: 'O ponto de partida'},
  {number: '02', title: 'Dos dados ao modelo', description: 'A organização das informações e as relações entre senadores, despesas e fornecedores.', anchor: 'modelagem-dos-dados', tag: 'A estrutura'},
  {number: '03', title: 'Consultas e análise', description: 'Perguntas sobre a distribuição das despesas, sua evolução e os padrões de gasto.', anchor: 'consultas-e-análise', tag: 'A investigação'},
];

export default function Home(): ReactNode {
  return (
    <Layout title="Dados públicos. Mais clareza." description="Inflow: documentação de um projeto acadêmico de banco de dados voltado à análise de gastos dos gabinetes dos senadores.">
      <main className={styles.home}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}><span className={styles.dot} /> PROJETO ACADÊMICO · BANCO DE DADOS</span>
          <Heading as="h1">Dados públicos.<br /><span>Mais clareza.</span></Heading>
          <p className={styles.intro}>Um olhar sobre os gastos dos gabinetes dos senadores.<br className={styles.desktopBreak} /> Da organização dos dados às perguntas que eles podem responder.</p>
          <div className={styles.actions}>
            <Link className={styles.primaryButton} to="/docs/intro">Explorar documentação <span aria-hidden="true">↗</span></Link>
            <a className={styles.textLink} href="#projeto">Conhecer o projeto <span aria-hidden="true">↓</span></a>
          </div>
          <div className={styles.overview}>
            <div className={styles.overviewTop}><span className={styles.wordmark}>inflow<span> / visão geral</span></span><span className={styles.outlineTag}>Da informação à compreensão</span></div>
            <div className={styles.flow}>
              <div className={styles.flowIntro}><span className={styles.smallLabel}>O PERCURSO DOS DADOS</span><Heading as="h2">Cada registro.<br />Uma parte da história.</Heading><p>Conectar informações para investigar o uso dos recursos públicos.</p></div>
              <ol className={styles.steps} aria-label="Etapas propostas para o projeto">
                <li><span className={styles.stepIcon} aria-hidden="true">01</span><div><strong>Reunir</strong><span>Fontes e registros de despesas</span></div></li>
                <li><span className={styles.stepIcon} aria-hidden="true">02</span><div><strong>Organizar</strong><span>Entidades, relações e banco de dados</span></div></li>
                <li><span className={styles.stepIcon} aria-hidden="true">03</span><div><strong>Investigar</strong><span>Consultas, comparações e contexto</span></div></li>
              </ol>
            </div>
            <div className={styles.overviewBottom}><span>Gastos parlamentares</span><span>Modelagem de dados</span><span>Análise exploratória</span></div>
          </div>
        </header>
        <section className={styles.project} id="projeto" aria-labelledby="project-title">
          <div className={styles.sectionHeading}><div><span className={styles.smallLabel}>POR DENTRO DO INFLOW</span><Heading as="h2" id="project-title">Entender começa<br />com boas perguntas.</Heading></div><p>Um projeto de banco de dados que aproxima técnica e transparência. Conheça a proposta e o caminho previsto para a análise.</p></div>
          <div className={styles.cards}>{chapters.map((chapter) => <Link key={chapter.number} to={`/docs/intro#${chapter.anchor}`} className={styles.card}><div className={styles.cardTop}><span>{chapter.number}</span><span aria-hidden="true">↗</span></div><Heading as="h3">{chapter.title}</Heading><p>{chapter.description}</p><span className={styles.cardTag}>{chapter.tag}</span></Link>)}</div>
        </section>
        <section className={styles.closing} aria-labelledby="closing-title"><span className={styles.smallLabel}>CONHECIMENTO DOCUMENTADO</span><Heading as="h2" id="closing-title">O caminho também importa.</Heading><p>Acompanhe a construção do projeto, suas decisões e possibilidades de análise.</p><Link className={styles.textLink} to="/docs/intro">Começar pela visão geral <span aria-hidden="true">→</span></Link></section>
      </main>
    </Layout>
  );
}
