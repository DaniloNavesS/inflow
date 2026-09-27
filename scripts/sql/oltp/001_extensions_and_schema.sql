-- PROJETO INTEGRADO: BANCO DE DADOS 2 (UnB - FCTE)
-- Plataforma InFlow: "Do dado bruto à decisão pública"
-- Módulo E1: Fonte Transacional (OLTP) - Dados Abertos do Senado Federal

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET timezone = 'UTC';

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS oltp;
