import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import styles from './index.module.css';

const chapters = [
  {number: '01', title: 'Escopo e perguntas', description: 'As perguntas válidas, o recorte e a situação de implementação da E1.', path: '/docs/escopo-e-perguntas', tag: 'O ponto de partida'},
  {number: '02', title: 'Dos dados ao modelo', description: 'As relações entre senadores, histórico, despesas, fornecedores e presença.', path: '/docs/arquitetura-pipeline', tag: 'A estrutura'},
  {number: '03', title: 'Fontes verificadas', description: 'APIs, endpoints e documentos oficiais usados na carga.', path: '/docs/fontes-e-endpoints', tag: 'A rastreabilidade'},
];

export default function Home(): ReactNode {
  return (
    <Layout title="Informação pública, mais perto de todos" description="O Mandato Aberto organiza e traduz dados públicos do Senado para facilitar o acesso da população brasileira a informações relevantes sobre seus representantes.">
      <main className={styles.home}>
        <header className={styles.hero}>
          <span className={styles.eyebrow}><span className={styles.dot} /> TRANSPARÊNCIA PARA A POPULAÇÃO BRASILEIRA</span>
          <Heading as="h1">Informação pública.<br /><span>Mais perto de todos.</span></Heading>
          <p className={styles.intro}>O Mandato Aberto organiza e traduz informações do Senado Federal para torná-las mais fáceis de encontrar, compreender e acompanhar. Os dados são públicos, mas ainda costumam estar dispersos e apresentados de forma técnica.</p>
          <div className={styles.actions}>
            <Link className={styles.primaryButton} to="/docs/intro">Explorar documentação <span aria-hidden="true">↗</span></Link>
            <a className={styles.textLink} href="#projeto">Entender o projeto <span aria-hidden="true">↓</span></a>
          </div>
          <div className={styles.overview}>
            <div className={styles.overviewTop}><span className={styles.wordmark}>Mandato Aberto<span>por que acompanhar</span></span><span className={styles.outlineTag}>Transparência que pode ser entendida</span></div>
            <div className={styles.flow}>
              <div className={styles.flowIntro}><span className={styles.smallLabel}>CIDADANIA E INFORMAÇÃO</span><Heading as="h2">Oito anos de mandato.<br />Decisões que atravessam o tempo.</Heading><p>Senadores são eleitos para mandatos de oito anos. Acompanhar sua atuação é tão importante quanto prestar atenção no momento do voto.</p></div>
              <ol className={styles.steps} aria-label="Motivos para acompanhar os dados do Senado">
                <li><span className={styles.stepIcon} aria-hidden="true">01</span><div><strong>Encontrar</strong><span>Dados abertos nem sempre são fáceis de localizar</span></div></li>
                <li><span className={styles.stepIcon} aria-hidden="true">02</span><div><strong>Compreender</strong><span>Registros técnicos precisam de contexto e linguagem clara</span></div></li>
                <li><span className={styles.stepIcon} aria-hidden="true">03</span><div><strong>Acompanhar</strong><span>Conhecer a atuação ajuda a fazer escolhas mais conscientes</span></div></li>
              </ol>
            </div>
            <div className={styles.overviewBottom}><span>Dados abertos</span><span>Mandatos de 8 anos</span><span>Escolha consciente</span></div>
          </div>
        </header>
        <section className={styles.project} id="projeto" aria-labelledby="project-title">
          <div className={styles.sectionHeading}><div><span className={styles.smallLabel}>POR DENTRO DO MANDATO ABERTO</span><Heading as="h2" id="project-title">Do dado aberto<br />à informação útil.</Heading></div><p>O projeto conecta fontes oficiais, organização de dados e perguntas de interesse público para aproximar transparência e cidadania.</p></div>
          <div className={styles.cards}>{chapters.map((chapter) => <Link key={chapter.number} to={chapter.path} className={styles.card}><div className={styles.cardTop}><span>{chapter.number}</span><span aria-hidden="true">↗</span></div><Heading as="h3">{chapter.title}</Heading><p>{chapter.description}</p><span className={styles.cardTag}>{chapter.tag}</span></Link>)}</div>
        </section>
        <section className={styles.closing} aria-labelledby="closing-title"><span className={styles.smallLabel}>CONHECIMENTO DOCUMENTADO</span><Heading as="h2" id="closing-title">O caminho também importa.</Heading><p>Acompanhe a construção do projeto, suas decisões e possibilidades de análise.</p><Link className={styles.textLink} to="/docs/intro">Começar pela visão geral <span aria-hidden="true">→</span></Link></section>
      </main>
    </Layout>
  );
}
