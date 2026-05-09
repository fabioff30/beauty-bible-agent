# Beauty Bible Agent 💄✨

**Agente de IA para recomendação de produtos de beleza via Telegram**

O Beauty Bible Agent é um bot do Telegram que analisa fotos da pele e recomenda os melhores produtos de beleza — skincare, cabelo, maquiagem e mais.

## Funcionalidades

- 📸 **Análise de Pele por IA** — Envie uma foto e o agente identifica tom, tipo, subtom e concerns
- 💄 **Recomendações Personalizadas** — Produtos ideais para seu tipo de pele e necessidades
- 📋 **Rotinas de Skincare** — Rotina completa: manhã, noite e semanal
- 💰 **Comparação de Preços** — Preços e especificações dos produtos
- 🧴 **Info de Ingredientes** — Explicações sobre cada ingrediente e seus benefícios

## Tecnologia

- **Telegram Bot API** — Interface primária do usuário
- **OpenRouter / OpenAI / Gemini** — APIS de IA para análise de imagem e conversação
- **Python 3.10+** — Linguagem principal
- **PIL + NumPy** — Fallback para análise básica sem IA

## Produtos Disponíveis

Linha **Dani** (skincare):
- Dani Radiance Serum (R$45)
- Dani Nourishing Night Cream (R$50)
- Dani Pure Cleansing Gel (R$25)
- Dani Glow Enhancing Moisturizer (R$35)
- Dani Firming Eye Cream (R$40)
- Dani Hydrating Mist (R$20)
- Dani Smooth Lip Balm (R$13)
- Dani Brightening Face Mask (R$30)
- Dani Gentle Exfoliating Scrub (R$18)

## Setup Rápido

```bash
# Clone
git clone https://github.com/fabioff30/beauty-bible-agent.git
cd beauty-bible-agent

# Setup Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edite .env com seu TELEGRAM_BOT_TOKEN e API keys

# Executar
python bot.py
```

## Configuração do Bot Telegram

1. Converse com [@BotFather](https://t.me/botfather) no Telegram
2. Envie `/newbot` e siga as instruções
3. Copie o token gerado para `TELEGRAM_BOT_TOKEN` no arquivo `.env`

## Provedores de IA

| Provedor | Custo | Qualidade | Setup |
|----------|-------|-----------|-------|
| OpenRouter | ~$0.15/1K img | ★★★★☆ | API key gratuita em openrouter.ai |
| OpenAI | ~$0.03/1K img | ★★★★★ | API key em platform.openai.com |
| Google Gemini | Grátis* | ★★★☆☆ | API key em aistudio.google.com |

*Gemini tem tier gratuito generoso para análise de imagem.

## Estrutura do Projeto

```
beauty-bible-agent/
├── bot.py              # Bot principal do Telegram
├── src/
│   ├── skin_analyzer.py   # Análise de pele (visão computacional + IA)
│   ├── product_db.py      # Catálogo de produtos + recomendações
│   └── agent.py           # Agente conversacional de beleza
├── data/
│   └── products.json      # Catálogo de produtos (JSON)
├── requirements.txt       # Dependências Python
└── .env.example           # Template de configuração
```

## Roadmap

- [ ] Integração com marketplace para preços em tempo real
- [ ] Suporte para análise de cabelo
- [ ] Recomendações de maquiagem por tom de pele
- [ ] Sistema de reviews por usuários
- [ ] Dashboard web para marcas cadastrarem produtos
- [ ] Integração com WhatsApp

## Autor

Criado para o pitch da **Beauty Bible** — Maio 2026.
