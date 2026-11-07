select id as estrutura_id, senador_id, ano, qtd_pessoal_gabinete,
       qtd_pessoal_escritorio, qtd_total_servidores, auxilio_moradia,
       imovel_funcional, atualizado_em
from {{ source('oltp', 'estrutura_gabinete') }}
