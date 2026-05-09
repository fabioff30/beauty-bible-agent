"""
Product Database - Catálogo de produtos de beleza
Baseado no catálogo Beauty Bible (Dani line)
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class ProductDatabase:
    """Manages the product catalog and recommendation logic"""

    def __init__(self, data_path: Optional[Path] = None):
        """
        Initialize product database
        
        Args:
            data_path: Path to JSON product catalog
        """
        self.data_path = data_path or Path(__file__).parent.parent / 'data' / 'products.json'
        self.products = self._load_products()

    def _load_products(self) -> List[Dict]:
        """Load products from JSON file"""
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Product data not found at {self.data_path}")
            return self._get_sample_products()
        except json.JSONDecodeError:
            logger.error("Invalid JSON in product data")
            return self._get_sample_products()

    def _get_sample_products(self) -> List[Dict]:
        """Return sample product catalog (Dani line from Beauty Bible pitch)"""
        return [
            # SKINCARE LINE
            {
                "id": "dani-radiance-serum",
                "name": "Dani Radiance Serum",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "serum",
                "description": "Sérum iluminador enriquecido com Vitamina C e Ácido Hialurônico que ilumina e hidrata, dando à pele um brilho saudável e radiante.",
                "ingredients": ["Vitamina C", "Ácido Hialurônico", "Niacinamida"],
                "price": 45.00,
                "skin_types": ["oleosa", "mista", "normal"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["manchas_escuras", "falta_firmeza", "textura_irregular"],
                "benefits": ["Ilumina", "Hidrata", "Uniformiza tom"],
                "image": "dani_radiance_serum.jpg"
            },
            {
                "id": "dani-nourishing-night-cream",
                "name": "Dani Nourishing Night Cream",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "creme_noturno",
                "description": "Creme noturno profundamente hidratante com Retinol e Óleos Essenciais que repara e rejuvenesce a pele enquanto você dorme, deixando-a macia e suave pela manhã.",
                "ingredients": ["Retinol", "Óleos Essenciais", "Vitamina E", "Ceramidas"],
                "price": 50.00,
                "skin_types": ["seca", "mista", "normal"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["linhas_expressao", "ressecamento", "falta_firmeza"],
                "benefits": ["Rejuvenesce", "Hidrata profundamente", "Repara"],
                "image": "dani_nourishing_night_cream.jpg"
            },
            {
                "id": "dani-pure-cleansing-gel",
                "name": "Dani Pure Cleansing Gel",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "limpeza",
                "description": "Gel de limpeza suave sem sulfato que remove impurezas e maquiagem eficazmente, mantendo a hidratação natural da pele. Ideal para uso diário.",
                "ingredients": ["Aloe Vera", "Glicerina", "Extrato de Chá Verde"],
                "price": 25.00,
                "skin_types": ["oleosa", "mista", "normal", "sensível"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["oleosidade_excessiva", "acne_espinhas", "poros_dilatados"],
                "benefits": ["Limpeza suave", "Equilibra oleosidade", "Não resseca"],
                "image": "dani_pure_cleansing_gel.jpg"
            },
            {
                "id": "dani-glow-enhancing-moisturizer",
                "name": "Dani Glow Enhancing Moisturizer",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "hidratante",
                "description": "Hidratante leve e não oleoso com Antioxidantes e Extratos Botânicos que realça o brilho natural da pele e proporciona hidratação o dia todo.",
                "ingredients": ["Antioxidantes", "Extratos Botânicos", "Vitamina B5"],
                "price": 35.00,
                "skin_types": ["seca", "mista", "normal"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["ressecamento", "falta_firmeza"],
                "benefits": ["Hidratação diária", "Brilho natural", "Leve"],
                "image": "dani_glow_moisturizer.jpg"
            },
            {
                "id": "dani-firming-eye-cream",
                "name": "Dani Firming Eye Cream",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "olhos",
                "description": "Creme para olhos eficiente com Peptídeos e Cafeína que reduz inchaço e linhas finas, dando aos olhos uma aparência jovem e revigorada.",
                "ingredients": ["Peptídeos", "Cafeína", "Vitamina K"],
                "price": 40.00,
                "skin_types": ["oleosa", "mista", "normal", "seca"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["olheiras", "linhas_expressao"],
                "benefits": ["Reduz olheiras", "Anti-idade", "Revigorante"],
                "image": "dani_firming_eye_cream.jpg"
            },
            {
                "id": "dani-hydrating-mist",
                "name": "Dani Hydrating Mist",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "spray",
                "description": "Spray facial refrescante com Aloe Vera e Água de Rosas que hidrata e acalma instantaneamente, perfeito para revitalizar durante o dia ou fixar maquiagem.",
                "ingredients": ["Aloe Vera", "Água de Rosas", "Ácido Hialurônico"],
                "price": 20.00,
                "skin_types": ["seca", "mista", "normal", "oleosa", "sensível"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["ressecamento", "vermelhidao"],
                "benefits": ["Hidratação instantânea", "Acalma", "Refresca"],
                "image": "dani_hydrating_mist.jpg"
            },
            {
                "id": "dani-smooth-lip-balm",
                "name": "Dani Smooth Lip Balm",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "labios",
                "description": "Bálsamo labial nutritivo enriquecido com Manteiga de Karité e Óleo de Jojoba que mantém seus lábios macios e hidratados com brilho sutil.",
                "ingredients": ["Manteiga de Karité", "Óleo de Jojoba", "Vitamina E"],
                "price": 13.00,
                "skin_types": ["oleosa", "mista", "normal", "seca", "sensível"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["ressecamento"],
                "benefits": ["Hidratação labial", "Brilho sutil", "Proteção"],
                "image": "dani_smooth_lip_balm.jpg"
            },
            {
                "id": "dani-brightening-face-mask",
                "name": "Dani Brightening Face Mask",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "mascara",
                "description": "Máscara facial clareadora que ilumina e revitaliza a pele cansada, deixando-a com aspecto radiante e saudável.",
                "ingredients": ["Argila Branca", "Extrato de Alcaçuz", "Niacinamida"],
                "price": 30.00,
                "skin_types": ["oleosa", "mista", "normal"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["manchas_escuras", "textura_irregular", "oleosidade_excessiva"],
                "benefits": ["Clareia manchas", "Revitaliza", "Textura suave"],
                "image": "dani_brightening_mask.jpg"
            },
            {
                "id": "dani-gentle-exfoliating-scrub",
                "name": "Dani Gentle Exfoliating Scrub",
                "brand": "Dani",
                "category": "skincare",
                "subcategory": "esfoliante",
                "description": "Esfoliante suave formulado com grãos finos de damasco e extrato calmante de camomila que remove células mortas deixando a pele suave e revitalizada.",
                "ingredients": ["Grãos de Damasco", "Extrato de Camomila", "Ácido Salicílico Suave"],
                "price": 18.00,
                "skin_types": ["oleosa", "mista", "normal"],
                "skin_tones": ["I", "II", "III", "IV", "V", "VI"],
                "concerns": ["textura_irregular", "poros_dilatados", "acne_espinhas"],
                "benefits": ["Remove células mortas", "Textura suave", "Poros limpos"],
                "image": "dani_gentle_exfoliating_scrub.jpg"
            }
        ]

    def get_recommendations(
        self,
        skin_tone: str = None,
        skin_type: str = None,
        concerns: List[str] = None,
        category: str = None,
        limit: int = 5
    ) -> List[Dict]:
        """
        Get product recommendations based on skin analysis
        
        Args:
            skin_tone: Fitzpatrick skin tone name
            skin_type: Skin type (oleosa, seca, mista, normal, sensível)
            concerns: List of skin concerns
            category: Product category filter
            limit: Max number of recommendations
            
        Returns:
            List of recommended products with match scores
        """
        scored_products = []
        
        for product in self.products:
            score = 0
            match_reasons = []
            
            # Match skin type (weight: 3)
            if skin_type and skin_type.lower() in [t.lower() for t in product.get('skin_types', [])]:
                score += 3
                match_reasons.append(f"Ideal para pele {skin_type}")
            
            # Match concerns (weight: 2 per concern)
            if concerns:
                product_concerns = [c.lower() for c in product.get('concerns', [])]
                matched_concerns = [c for c in concerns if c.lower() in product_concerns]
                score += len(matched_concerns) * 2
                if matched_concerns:
                    match_reasons.append(f"Trata: {', '.join(matched_concerns)}")
            
            # Match category (weight: 1)
            if category and category.lower() == product.get('category', '').lower():
                score += 1
            
            if score > 0:
                scored_products.append({
                    **product,
                    'match_score': score,
                    'match_reasons': match_reasons
                })
        
        # Sort by score and return top N
        scored_products.sort(key=lambda x: x['match_score'], reverse=True)
        return scored_products[:limit]

    def get_product_by_id(self, product_id: str) -> Optional[Dict]:
        """Get product details by ID"""
        for product in self.products:
            if product['id'] == product_id:
                return product
        return None

    def get_routine(
        self,
        skin_tone: str = None,
        skin_type: str = None,
        budget: str = 'medium'
    ) -> Dict[str, List]:
        """
        Generate a complete skincare routine based on skin type and budget
        
        Args:
            skin_tone: User's skin tone
            skin_type: User's skin type
            budget: 'low', 'medium', or 'high'
            
        Returns:
            Dict with morning and night routines
        """
        # Get recommendations by subcategory
        routine = {
            'morning': [],
            'night': [],
            'weekly': [],
            'total_price': 0
        }
        
        morning_categories = ['limpeza', 'hidratante', 'serum']
        night_categories = ['limpeza', 'creme_noturno', 'olhos']
        weekly_categories = ['mascara', 'esfoliante']
        
        for subcat in morning_categories:
            recs = self.get_recommendations(
                skin_type=skin_type,
                limit=1
            )
            if recs:
                routine['morning'].append(recs[0])
                routine['total_price'] += recs[0]['price']
        
        for subcat in night_categories:
            recs = self.get_recommendations(
                skin_type=skin_type,
                limit=1
            )
            if recs:
                routine['night'].append(recs[0])
                routine['total_price'] += recs[0]['price']
        
        for subcat in weekly_categories:
            recs = self.get_recommendations(
                skin_type=skin_type,
                limit=1
            )
            if recs:
                routine['weekly'].append(recs[0])
                routine['total_price'] += recs[0]['price']
        
        return routine