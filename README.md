# 📊 CEMIDASH – Dashboard Educacional Automatizado

O **CEMIDASH** é um sistema desenvolvido para automatizar a leitura de planilhas de avaliações escolares, processar dados e apresentar resultados organizados através de um dashboard intuitivo.  
O projeto resolve um problema comum em instituições de ensino: **a dependência de planilhas manuais**, que causam atrasos, erros e retrabalho na análise do desempenho estudantil.

Este repositório contém o módulo responsável pela **leitura, processamento e integração de dados** usando **Python + Django**.

------------------------------------------------------------------------

## 🚀 Objetivo do Projeto

- Automatizar a coleta, leitura e processamento de dados de avaliações (Prova 1, Prova 2, Simulados etc.)
- Reduzir o tempo gasto com tarefas manuais
- Fornecer indicadores visuais claros sobre o desempenho dos alunos
- Auxiliar professores, coordenadores e diretores na tomada de decisões pedagógicas
- Promover o uso de dados reais na gestão educacional
  
------------------------------------------------------------------------

## 🧠 Funcionalidades

✔ Upload de planilhas (.xlsx)  
✔ Leitura automática de dados usando `openpyxl`  
✔ Processamento de métricas (médias, acertos, erros, porcentagens etc.)  
✔ Classificação automática de desempenho:  
- **Excelente**  
- **Médio**  
- **Crítico**

✔ Geração de dados para visualização no dashboard  
✔ Suporte a gráficos e indicadores visuais  
✔ Armazenamento em banco SQLite  
✔ Interface desenvolvida em Django Template

------------------------------------------------------------------------

## 🛠 Tecnologias Utilizadas

### **Back-end**
- Python **3.14**
- Django **5**

### **Bibliotecas**
- `openpyxl` – leitura de planilhas Excel  
- `Pillow` – suporte a imagens no Django  
- SQLite – banco de dados padrão do Django  

### **Front-end**
- Django Templates (HTML, CSS e estilização personalizada)
