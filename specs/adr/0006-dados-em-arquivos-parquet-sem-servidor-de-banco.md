# ADR-0006 — Guardar os dados em arquivos Parquet locais, sem servidor de banco

**Status:** aceito (2026-10-07, com o gate de design da Fase 1)
**Data:** 2026-10-06
**Contexto de decisão:** Fase 1 — design (armazenamento)

## Contexto

A fase guarda quatro famílias de dado: fills de alguns milhares de carteiras, funding e lotes, o preço proxy por segundo e o que o coletor grava do livro. As três primeiras são pequenas. A quarta não é: o canal de melhor compra e venda chega várias vezes por segundo nos ativos líquidos, e a lista do coletor tem 27 ativos ou mais. Pela cadência medida na verificação, 45 dias dão algo da ordem de centenas de milhões de linhas. É estimativa, não medida.

O padrão de uso é sempre o mesmo. Cada tabela é escrita uma vez, por um único processo, e depois lida em bloco, por janela de tempo. Não há atualização de linha, não há leitura concorrente com escrita, não há consulta por chave avulsa.

Três requisitos pesam na escolha. O coletor roda numa máquina doméstica e precisa sobreviver a queda de energia sem perder o que já gravou (premissa 13). O disco total da fase é de 30 GB (RNF-10). E todo resultado registra um hash determinístico dos dados que consumiu (RF-ING-08), que o congelamento usa para recusar uma avaliação sobre dado diferente (RF-SEL-05).

Antes da verificação de dados, a sugestão inicial de arquitetura era um PostgreSQL local em Docker. Ela foi feita sem a cadência medida e fica revista aqui.

## Decisão

1. **Sem servidor de banco.** Os dados ficam em arquivos, sob um diretório configurado (`COPYLAB_DATA_DIR`), fora do git. Não há `docker-compose`.
2. **Tabelas em Parquet**, comprimidas, particionadas pela chave natural de leitura: endereço para fills, ativo e dia para preço e livro.
3. **Dado bruto não é editado.** O corpo do leaderboard é guardado como chegou. Os segmentos do coletor são gravados como chegaram e só são descartados depois que a compactação confere as contagens contra eles, por causa do orçamento de disco. A partir daí a tabela compactada é o registro.
4. **Escrita atômica.** Toda tabela é escrita em arquivo temporário e trocada de nome ao fim.
5. **Hash pelo conteúdo.** O hash de um conjunto de dados é calculado dos valores, em ordem canônica, e nunca dos bytes do arquivo.
6. **Dado congelado não muda.** Linha dentro de uma janela que algum congelamento cobre nunca é reescrita. Uma coleta nova que divirja dela é registrada à parte.
7. **Uma única porta.** Só `copylab.storage` conhece o diretório de dados e o formato. Livro-razão, seleção, simulador e analytics leem por um protocolo de leitura, sem conhecer arquivo nem diretório, e não gravam nada: devolvem objetos, texto ou bytes, e quem grava é a CLI.

Arquivos de pré-registro, congelamentos e relatórios não são dados neste sentido: são texto, pequenos, e vão para o git.

## Justificativa

- **O formato combina com o uso.** Escrita única e leitura em bloco por janela é o caso para o qual o formato colunar foi feito. Uma simulação lê algumas colunas de alguns dias de um ativo, e é isso que o particionamento entrega sem índice.
- **Ocupa menos disco.** Colunas de preço e de tempo comprimem muito bem, e um banco relacional guarda por linha e ainda soma os índices. O orçamento de 30 GB continua em risco mesmo assim: quem mede é o primeiro dia de coletor.
- **O coletor fica simples.** Ele só acrescenta bytes a um arquivo e o fecha de hora em hora. Não depende de um segundo processo estar no ar, e uma queda custa no máximo o fim do segmento aberto.
- **O hash vira propriedade do dado.** Reescrever o mesmo conteúdo, com outra versão de biblioteca ou outra compressão, não muda o hash. Com isso o congelamento continua valendo depois de uma reingestão idêntica, e deixa de valer se um único valor mudar.
- **Mover dado é copiar pasta.** O coletor roda numa máquina e a análise pode rodar em outra. A cópia é conferida pelo mesmo hash.
- **A suíte não precisa de serviço.** `make test` roda offline e sem contêiner, e o CI continua com um job só.

**Onde a escolha é pior.** Não há consulta SQL pronta para explorar o dado: quem quiser olhar precisa abrir um caderno ou apontar uma ferramenta de consulta para os arquivos. Não há restrição de integridade garantida pelo banco, então toda validação precisa estar no código da borda. Dois processos não podem escrever a mesma tabela. E o projeto deixa de exercitar PostgreSQL, que seria um ponto a favor num portfólio.

## Alternativas descartadas

**PostgreSQL local em Docker.** É o banco que o Pedro já usa, tem SQL, restrições e ferramentas maduras. Descartada porque, pela conta de linhas, o livro com índices tende a passar do orçamento de disco, o que não foi medido, porque a carga é de escrita única e leitura em bloco, que não usa nada do que um banco transacional oferece, e porque o coletor passaria a depender de um contêiner estar no ar numa máquina doméstica.

**TimescaleDB.** Resolve parte do volume, com compressão colunar por trás de uma tabela de série temporal, e mantém o SQL. Descartada porque continua sendo um servidor para operar, e a compressão dela exige uma política de janelas que é mais uma coisa a acertar e testar. Ganha-se SQL, que esta fase não usa.

**PostgreSQL gerenciado gratuito (Supabase).** Não exige máquina nem contêiner. Descartada porque o plano gratuito tem 500 MB de banco e pausa o projeto depois de uma semana sem uso, conforme a página de preços consultada em 2026-10-06. Os dados desta fase são dezenas de vezes maiores.

**SQLite.** Um arquivo só, sem servidor, com SQL. Descartada para as tabelas grandes porque guarda por linha: o livro ocuparia muito mais disco e a leitura de uma coluna por janela seria mais lenta. Para as tabelas pequenas funcionaria, mas dois formatos de armazenamento custam mais do que um.

**MongoDB, como no quantlab.** Aproveitaria a experiência do outro projeto. Descartada porque lá o dado era diário e pequeno. Aqui o volume é ordens de grandeza maior, e documento por linha é o formato menos compacto de todos.

**Guardar só o bruto, em texto comprimido.** É o mais simples e o mais fiel. Descartada como formato de leitura porque cada simulação teria que interpretar texto de novo. Foi mantida como formato de gravação do coletor, que é onde a simplicidade importa.

## Consequências

- `polars` entra como dependência de runtime.
- RNF-06 deixa de citar serviços (requisitos 1.2).
- O diretório de dados não tem cópia de segurança automática. Perder o disco do coletor é perder a janela prospectiva, e isso fica a cargo de quem opera a máquina.
- Explorar o dado à mão passa a ser feito com caderno ou com uma ferramenta de consulta sobre os arquivos, fora do pacote.
- A validação de formato e de integridade mora nos provedores e na compactação do coletor, e precisa de teste próprio.
- O piloto vai precisar de estado transacional (ordens enviadas, confirmações). A spec dele decide o próprio armazenamento, e este ADR não o prende.

## Invariantes que o código precisa respeitar

| Invariante | Teste que prova |
|---|---|
| O hash não depende dos bytes do arquivo nem da ordem de escrita das linhas | `test_content_hash_ignores_file_bytes_and_row_order` |
| A mudança de um único valor muda o hash e é logada com o valor anterior e o novo | `test_changed_fill_is_logged_and_changes_hash` |
| Uma escrita interrompida deixa a tabela anterior intacta | `test_interrupted_write_leaves_previous_table_intact` |
| Um snapshot bruto nunca é sobrescrito | `test_leaderboard_snapshot_is_timestamped_hashed_and_never_overwritten` |
| Linha dentro de uma janela congelada nunca é reescrita | `test_frozen_rows_are_never_rewritten` |
| Fora de `copylab.storage`, nenhum módulo lê ou escreve Parquet nem conhece o diretório de dados | `test_architecture_storage_isolation` |

## Revisitar quando

Houver mais de um processo escrevendo a mesma tabela. Os dados deixarem de caber no disco de uma máquina. Uma fase posterior expuser consulta concorrente, como uma API ou um dashboard. Ou a exploração manual do dado virar rotina a ponto de justificar um banco de consulta ao lado dos arquivos.
