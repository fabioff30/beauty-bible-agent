"""
Skin Analyzer - AI-powered skin analysis module
Reconhece tom de pele, tipo, subtom e concerns usando visão computacional
"""

import os
import base64
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SkinAnalyzer:
    """
    Analyzes user photos to determine:
    - Skin tone (Fitzpatrick scale I-VI)
    - Skin type (oily, dry, combination, normal)
    - Undertone (warm, cool, neutral)
    - Skin concerns (acne, aging, hyperpigmentation, etc.)
    """

    # Fitzpatrick scale color ranges (HEX)
    SKIN_TONES = {
        'I': {'name': 'Muito Clara', 'description': 'Sempre queima, nunca bronzeia', 'hex_range': ['#FCE4D6', '#FDF2E9']},
        'II': {'name': 'Clara', 'description': 'Geralmente queima, bronzeia pouco', 'hex_range': ['#F5CBA7', '#FADBD8']},
        'III': {'name': 'Média Clara', 'description': 'Às vezes queima, bronzeia gradualmente', 'hex_range': ['#E8B88A', '#EDBB99']},
        'IV': {'name': 'Média / Morena', 'description': 'Raramente queima, bronzeia facilmente', 'hex_range': ['#BA815A', '#C68E64']},
        'V': {'name': 'Morena Escura', 'description': 'Muito raramente queima, bronzeia muito', 'hex_range': ['#8D5524', '#A26A3A']},
        'VI': {'name': 'Escura / Negra', 'description': 'Nunca queima, profundamente pigmentada', 'hex_range': ['#5C3A21', '#704B2A']}
    }

    SKIN_TYPES = {
        'oily': 'Oleosa',
        'dry': 'Seca',
        'combination': 'Mista',
        'normal': 'Normal',
        'sensitive': 'Sensível'
    }

    UNDERTONES = {
        'warm': 'Quente (amarelado/dourado)',
        'cool': 'Frio (rosado/azulado)',
        'neutral': 'Neutro',
        'olive': 'Oliva'
    }

    CONCERNS = [
        'acne_espinhas',
        'manchas_escuras',
        'linhas_expressao',
        'poros_dilatados',
        'vermelhidao',
        'oleosidade_excessiva',
        'ressecamento',
        'falta_firmeza',
        'olheiras',
        'textura_irregular'
    ]

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize skin analyzer
        
        Args:
            api_key: OpenAI or OpenRouter API key
        """
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY') or os.getenv('OPENAI_API_KEY')
        self.model = os.getenv('VISION_MODEL', 'google/gemini-2.5-flash')

    async def analyze(self, image_path: Path) -> dict:
        """
        Analyze a photo to determine skin characteristics.
        Goes through OpenRouter (or OpenAI directly if AI_PROVIDER=openai).
        Falls back to a local color-based heuristic only if the API call fails.
        """
        try:
            return await self._analyze_with_vision_api(image_path)
        except Exception as e:
            logger.warning(f"Vision API analysis failed: {e}")

        logger.info("Using basic color analysis as fallback")
        return self._analyze_with_basic(image_path)

    async def _analyze_with_vision_api(self, image_path: Path) -> dict:
        """Analyze using OpenRouter (default) or OpenAI Vision endpoints."""
        import httpx

        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        provider = os.getenv('AI_PROVIDER', 'openrouter')
        if provider == 'openai':
            api_url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                "Content-Type": "application/json",
            }
        else:
            # Default: OpenRouter. Gemini models like google/gemini-3.1-flash-lite
            # are routed through OpenRouter — no separate Google SDK needed.
            api_url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
                "HTTP-Referer": "https://beautybible.app",
                "X-Title": "Beauty Bible",
                "Content-Type": "application/json",
            }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
                        },
                        {
                            "type": "text",
                            "text": self._get_analysis_prompt(),
                        },
                    ],
                }
            ],
            "max_tokens": 500,
            "temperature": 0.3,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data['choices'][0]['message']['content']
            return self._parse_response(content)

    def _analyze_with_basic(self, image_path: Path) -> dict:
        """Basic color-based analysis (no AI)"""
        try:
            from PIL import Image
            import numpy as np
            from collections import Counter
            
            img = Image.open(image_path).convert('RGB')
            img = img.resize((100, 100))  # Reduce for performance
            pixels = np.array(img)
            
            # Reshape to list of pixels
            pixels_list = pixels.reshape(-1, 3)
            
            # Get dominant colors
            from sklearn.cluster import KMeans
            kmeans = KMeans(n_clusters=3, n_init=10)
            kmeans.fit(pixels_list)
            dominant_colors = kmeans.cluster_centers_
            
            # Average color
            avg_color = np.mean(dominant_colors, axis=0)
            hex_color = '#{:02x}{:02x}{:02x}'.format(int(avg_color[0]), int(avg_color[1]), int(avg_color[2]))
            
            # Simple brightness-based tone classification
            brightness = np.mean(avg_color)
            
            if brightness > 200:
                skin_tone = 'I'
            elif brightness > 180:
                skin_tone = 'II'
            elif brightness > 150:
                skin_tone = 'III'
            elif brightness > 120:
                skin_tone = 'IV'
            elif brightness > 90:
                skin_tone = 'V'
            else:
                skin_tone = 'VI'
            
            return {
                'skin_tone': self.SKIN_TONES[skin_tone]['name'],
                'skin_tone_fitzpatrick': skin_tone,
                'skin_type': 'normal',  # Can't determine from image alone
                'undertone': 'neutral',
                'concerns': [],
                'confidence': 'baixa (análise básica sem IA)',
                'hex_color': hex_color
            }
            
        except ImportError as e:
            logger.error(f"Basic analysis requires additional packages: {e}")
            return {
                'skin_tone': 'Não identificada',
                'skin_type': 'Não identificado',
                'undertone': 'Não identificado',
                'concerns': [],
                'confidence': 'N/D',
                'error': str(e)
            }

    def _get_analysis_prompt(self) -> str:
        """Get the standardized analysis prompt"""
        return """Analise esta foto de pele e retorne APENAS um JSON válido (sem markdown, sem explicações):

{
  "skin_tone": "Fitzpatrick I a VI",
  "skin_tone_name": "Nome da classificação Fitzpatrick em português",
  "skin_type": "seca|oleosa|mista|normal|sensível",
  "undertone": "quente|frio|neutro|oliva",
  "concerns": ["lista", "de", "concerns"],
  "overall_health": "Descrição breve da saúde da pele",
  "confidence": "alta|média|baixa"
}

Classificação Fitzpatrick:
- I: Muito clara (sempre queima, nunca bronzeia)
- II: Clara (geralmente queima, bronzeia pouco)
- III: Média clara (às vezes queima, bronzeia gradualmente)
- IV: Média / Morena (raramente queima, bronzeia facilmente)
- V: Morena escura (muito raramente queima)
- VI: Escura / Negra (nunca queima)

Concerns possíveis: acne, manchas, linhas de expressão, poros dilatados, vermelhidão, oleosidade, ressecamento, falta de firmeza, olheiras, textura irregular.

Responda SOMENTE o JSON, nada mais."""

    def _parse_response(self, content: str) -> dict:
        """Parse AI response to standardized format"""
        try:
            # Clean up markdown code blocks if present
            content = content.strip()
            if content.startswith('```'):
                content = content.split('\n', 1)[1]
                if content.endswith('```'):
                    content = content[:-3]
            if content.lower().startswith('json'):
                content = content[4:]
            content = content.strip()
            
            # Parse JSON
            data = json.loads(content)
            
            # Map to standardized format
            skin_tone_map = {
                'I': 'Muito Clara',
                'II': 'Clara', 
                'III': 'Média Clara',
                'IV': 'Média / Morena',
                'V': 'Morena Escura',
                'VI': 'Escura / Negra'
            }
            
            result = {
                'skin_tone': data.get('skin_tone_name') or data.get('skin_tone', 'Não identificada'),
                'skin_tone_fitzpatrick': data.get('skin_tone', 'III'),
                'skin_type': self.SKIN_TYPES.get(data.get('skin_type', '').lower(), data.get('skin_type', 'Normal')),
                'undertone': self.UNDERTONES.get(data.get('undertone', '').lower(), data.get('undertone', 'Neutro')),
                'concerns': data.get('concerns', []),
                'overall_health': data.get('overall_health', ''),
                'confidence': data.get('confidence', 'média')
            }
            
            return result
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse AI response: {e}")
            logger.debug(f"Raw content: {content}")
            return {
                'skin_tone': 'Não identificada',
                'skin_type': 'Não identificado',
                'undertone': 'Não identificado',
                'concerns': [],
                'confidence': 'erro_analise',
                'raw_response': content[:200]
            }