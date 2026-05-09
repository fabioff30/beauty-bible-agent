# Beauty Bible Agent

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

**Beauty Bible Agent** is a Telegram bot powered by AI that analyzes user skin photos and recommends beauty products. The system:

- Receives photos via Telegram and analyzes skin tone, type, undertone, and concerns
- Uses OpenRouter/OpenAI/Gemini Vision APIs for skin analysis  
- Maintains a product catalog (starting with the Dani skincare line)
- Generates personalized skincare routines and product recommendations
- Supports Portuguese (BR) as primary language

## Architecture

```
beauty-bible-agent/
├── bot.py                  # Telegram bot entry point
├── src/
│   ├── __init__.py
│   ├── skin_analyzer.py    # AI-powered skin photo analysis
│   ├── product_db.py       # Product catalog & recommendation engine
│   └── agent.py            # Conversational AI beauty advisor
├── data/
│   └── products.json       # Product catalog (JSON)
├── tests/
│   └── __init__.py
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variables template
└── README.md               # Documentation
```

### Core Flow
1. **User sends photo** → `bot.py` → `handle_photo()`
2. **Photo downloaded** locally to `data/user_photos/`
3. **SkinAnalyzer.analyze()** calls AI Vision API to detect:
   - Fitzpatrick skin tone (I-VI)
   - Skin type (oily/dry/combination/normal/sensitive)
   - Undertone (warm/cool/neutral/olive)
   - Concerns (acne, hyperpigmentation, aging, etc.)
4. **ProductDatabase.get_recommendations()** scores products by skin match
5. **Results delivered** as formatted Telegram message
6. **Conversation continues** via `BeautyAdvisorAgent.get_response()`

### Fallback Strategy
Skin analysis has 3 tiers:
1. **Google Gemini** (free, good vision) — `_analyze_with_gemini()`
2. **OpenRouter/OpenAI Vision** (paid, best quality) — `_analyze_with_openai()`  
3. **Basic color analysis** (no AI needed) — `_analyze_with_basic()` using PIL + KMeans clustering

## Development Commands

### Setup
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and API keys
```

### Run the bot
```bash
python bot.py
```

### Run tests
```bash
pytest tests/ -v
```

## Product Database

Products are stored in `data/products.json`. Current catalog: Dani skincare line (9 products from the Beauty Bible pitch deck).

### Product Schema
```json
{
  "id": "dani-radiance-serum",
  "name": "Dani Radiance Serum",
  "brand": "Dani",
  "category": "skincare",
  "subcategory": "serum",
  "description": "...",
  "ingredients": ["Vitamina C", "..."],
  "price": 45.00,
  "skin_types": ["oleosa", "mista", "normal"],
  "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
  "concerns": ["manchas_escuras", "..."],
  "benefits": ["Ilumina", "..."],
  "image": "dani_radiance_serum.jpg"
}
```

### Available Subcategories
- `limpeza` (cleanser)
- `serum` (serum)
- `hidratante` (moisturizer)
- `creme_noturno` (night cream)
- `olhos` (eye cream)
- `spray` (facial mist)
- `labios` (lip balm)
- `mascara` (face mask)
- `esfoliante` (exfoliator)

### Skin Concerns Mapping
- `acne_espinhas` → acne/breakouts
- `manchas_escuras` → dark spots/hyperpigmentation
- `linhas_expressao` → fine lines/wrinkles
- `poros_dilatados` → enlarged pores
- `vermelhidao` → redness/sensitivity
- `oleosidade_excessiva` → excess oil
- `ressecamento` → dryness
- `falta_firmeza` → loss of firmness
- `olheiras` → dark circles
- `textura_irregular` → uneven texture

## Key Patterns

### Error Handling
- All async operations wrapped in try/except with user-friendly error messages
- AI API failures fall back to basic analysis or offline responses
- Non-critical failures (ingredient lookup) should not break conversation flow

### Language
- All user-facing text must be in Portuguese (BR)
- Code comments and logging in English

### Adding New Products
1. Add entry to `data/products.json` or `product_db._get_sample_products()`
2. Ensure proper categorization (category, subcategory)
3. Map to relevant skin types, concerns, and tones
4. Test with `get_recommendations()` for each skin type

### Extending Categories
To add a new category (e.g., hair, nails, makeup):
1. Add category enum to product schema
2. Update `get_routine()` logic
3. Add products with the new category
4. Update agent's system prompt to include new domain knowledge
