# -*- coding: utf-8 -*-
"""
groq_integration.py - الإصدار v4.1.1
🔧 التعديلات v4.1.1:
   - 🔥 إصلاح تكرار اللوجات (إزالة handler المكرر)
🔧 الإصدار السابق:
   - إرسال بيانات حقيقية كاملة لـ Groq
   - prompt محسن
"""

import logging
import json
import traceback
import requests
import re

from config import (
    GROQ_API_KEY, ENABLE_GROQ_ANALYSIS, GROQ_MODEL,
    GROQ_API_BASE_URL, GROQ_SEND_FULL_DATA
)

# 🔥 لا نضيف handler — root logger في bot_enhanced.py يتولى ذلك
logger = logging.getLogger("groq_integration")
logger.setLevel(logging.INFO)

groq_available = False
client = None
_client_type = None


def _try_init_groq_library():
    """تهيئة Groq بالمكتبة الرسمية"""
    global groq_available, client, _client_type

    try:
        import groq
        logger.info("تم استيراد groq")

        try:
            client = groq.Groq(api_key=GROQ_API_KEY)
            _client_type = "Groq"
            groq_available = True
            logger.info("✅ تهيئة Groq (Groq)")
            return True
        except Exception as e:
            logger.warning(f"محاولة 1 فشلت: {e}")

        try:
            client = groq.Client(api_key=GROQ_API_KEY)
            _client_type = "Client"
            groq_available = True
            logger.info("✅ تهيئة Groq (Client)")
            return True
        except Exception as e:
            logger.warning(f"محاولة 2 فشلت: {e}")

        return False

    except ImportError:
        return False
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return False


def _init_groq_http_fallback():
    """بديل HTTP"""
    global groq_available, client, _client_type

    if not GROQ_API_KEY:
        return False

    class GroqHTTPClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.base_url = "https://api.groq.com/openai/v1"
            self.headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

        def chat_completions_create(self, model, messages, temperature=0.3,
                                    max_tokens=1000, top_p=0.9):
            url = f"{self.base_url}/chat/completions"
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p
            }

            response = requests.post(url, headers=self.headers, json=payload, timeout=45)
            response.raise_for_status()
            return response.json()

    try:
        test_client = GroqHTTPClient(GROQ_API_KEY)
        test_payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5
        }

        test_response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=test_client.headers,
            json=test_payload,
            timeout=15
        )

        if test_response.status_code == 200:
            client = test_client
            _client_type = "http_client"
            groq_available = True
            logger.info("✅ تهيئة HTTP")
            return True
        else:
            logger.error(f"فشل اختبار: {test_response.status_code}")
            return False

    except Exception as e:
        logger.error(f"فشل HTTP: {e}")
        return False


def _init_simple_http_client():
    """عميل بسيط"""
    global groq_available, client, _client_type

    class SimpleGroqClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.base_url = "https://api.groq.com/openai/v1"
            self.headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

        def chat_completions_create(self, **kwargs):
            url = f"{self.base_url}/chat/completions"
            response = requests.post(url, headers=self.headers, json=kwargs, timeout=45)
            response.raise_for_status()
            return response.json()

    try:
        client = SimpleGroqClient(GROQ_API_KEY)
        _client_type = "simple_http"
        groq_available = True
        logger.info("✅ تهيئة بسيطة")
        return True
    except Exception as e:
        logger.error(f"فشل: {e}")
        return False


# ==================== التهيئة ====================
if ENABLE_GROQ_ANALYSIS and GROQ_API_KEY:
    logger.info("🔄 تهيئة Groq...")

    if not _try_init_groq_library():
        if not _init_groq_http_fallback():
            if not _init_simple_http_client():
                logger.error("❌ فشل كل المحاولات")
            else:
                logger.info("✅ تهيئة بسيطة")
        else:
            logger.info("✅ تهيئة HTTP")
    else:
        logger.info("✅ تهيئة رسمية")
else:
    if not ENABLE_GROQ_ANALYSIS:
        logger.info("ℹ️ Groq معطل")
    if not GROQ_API_KEY:
        logger.warning("⚠️ مفتاح مفقود")


def extract_json_from_response(response_content):
    """استخراج JSON"""
    try:
        json_pattern = r'\{[\s\S]*\}'
        matches = re.findall(json_pattern, response_content)

        if matches:
            return max(matches, key=len)

        code_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        code_matches = re.findall(code_block_pattern, response_content)

        if code_matches:
            return code_matches[0]

        return None

    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


def parse_groq_response(response_content):
    """تحليل الاستجابة"""
    try:
        if not response_content:
            return None

        json_str = extract_json_from_response(response_content)

        if json_str:
            groq_data = json.loads(json_str)

            required = ['recommendation', 'confidence', 'analysis']
            if all(k in groq_data for k in required):
                result = {
                    'groq_recommendation': groq_data['recommendation'],
                    'groq_confidence': groq_data['confidence'],
                    'groq_analysis': groq_data['analysis'],
                    'groq_reasoning': groq_data.get('reasoning', 'لا توجد أسباب'),
                    'groq_risk_level': groq_data.get('risk_level', 'متوسط')
                }
                logger.info(f"✅ Groq: {result['groq_recommendation']} ({result['groq_confidence']}%)")
                return result
            else:
                return {
                    'groq_recommendation': groq_data.get('recommendation', 'تحذير'),
                    'groq_confidence': groq_data.get('confidence', 50),
                    'groq_analysis': groq_data.get('analysis', response_content[:300]),
                    'groq_reasoning': groq_data.get('reasoning', ''),
                    'groq_risk_level': groq_data.get('risk_level', 'متوسط')
                }

        recommendation = "تحذير"
        confidence = 50

        if "تأكيد" in response_content or "موافق" in response_content:
            recommendation = "تأكيد"
            confidence = 75
        elif "رفض" in response_content or "تجنب" in response_content:
            recommendation = "رفض"
            confidence = 65

        confidence_pattern = r'ثقة[:\s]*(\d+)'
        match = re.search(confidence_pattern, response_content)
        if match:
            confidence = int(match.group(1))

        return {
            'groq_recommendation': recommendation,
            'groq_confidence': confidence,
            'groq_analysis': response_content[:400],
            'groq_reasoning': 'تحليل نصي',
            'groq_risk_level': 'متوسط'
        }

    except json.JSONDecodeError as e:
        logger.error(f"خطأ JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


def build_rich_prompt(signal_data, analysis_data=None):
    """بناء prompt غني بالبيانات الحقيقية"""
    try:
        symbol = signal_data.get('symbol', 'UNKNOWN')
        direction = signal_data.get('direction', 'UNKNOWN')
        confidence = signal_data.get('confidence', 0)
        strength = signal_data.get('strength', 0)
        entry_price = signal_data.get('entry_price', 0)

        analysis = analysis_data or signal_data.get('analysis', {})

        technical = analysis.get('technical_indicators', {})
        volume = analysis.get('volume_analysis', {})
        timeframes = analysis.get('timeframes', {})
        momentum = analysis.get('momentum', {})
        price_action = analysis.get('price_action', {})

        rsi = technical.get('rsi', 0)
        macd_trend = technical.get('macd_trend', 'محايد')
        vol_ratio = volume.get('volume_5m_ratio', 0)
        vol_conf = volume.get('volume_confidence', 'غير معروف')

        tf_summary = []
        for tf in ['1m', '3m', '5m', '15m']:
            if tf in timeframes:
                t = timeframes[tf]
                tf_summary.append(f"{tf}: {t.get('trend', 'محايد')} ({t.get('trend_strength', 0):.1f}/10)")
        tf_text = "\n".join(tf_summary) if tf_summary else "غير متاح"

        mom_dir = momentum.get('direction', 'محايد')
        mom_strength = momentum.get('strength', 0)

        candle_type = price_action.get('candle_type', 'غير معروف')
        body_strength = price_action.get('body_strength', 'غير معروف')

        alignment = signal_data.get('timeframe_alignment', 0)
        volatility = technical.get('volatility', 'غير معروف')

        prompt = f"""أنت محلل فني خبير في تداول العملات الرقمية. قم بتحليل الإشارة التالية بعمق:

📊 **بيانات الإشارة:**
- العملة: {symbol}
- الاتجاه المقترح: {direction}
- السعر الحالي: {entry_price}
- ثقة النظام: {confidence:.1f}%
- قوة الإشارة: {strength}/10

📈 **المؤشرات الفنية:**
- RSI (14): {rsi:.2f}
- MACD: {macd_trend}
- Volatility: {volatility}

📊 **تحليل الحجم:**
- نسبة الحجم (5m): {vol_ratio:.2f}x
- ثقة الحجم: {vol_conf}

⏰ **تحليل الأطر الزمنية:**
{tf_text}

⏰ **ترابط الفريمات:** {alignment:.1f}/10

📉 **الزخم:**
- الاتجاه: {mom_dir}
- القوة: {mom_strength:.1f}/10

🕯️ **حركة السعر:**
- نوع الشمعة: {candle_type}
- قوة الجسم: {body_strength}

---

**المطلوب منك:**

1. هل تؤكد هذه الإشارة أم ترفضها؟ (تأكيد/تحذير/رفض)
2. ما مستوى ثقتك؟ (0-100)
3. تحليل موجز (2-3 جمل)
4. الأسباب المنطقية (3-4 نقاط)
5. مستوى المخاطرة (عالي/متوسط/منخفض)

**أجب بصيغة JSON فقط:**
{{
  "recommendation": "تأكيد" أو "تحذير" أو "رفض",
  "confidence": رقم من 0 إلى 100,
  "analysis": "تحليل موجز",
  "reasoning": "نقاط الأسباب",
  "risk_level": "عالي" أو "متوسط" أو "منخفض"
}}

JSON فقط، بدون نص إضافي."""

        return prompt

    except Exception as e:
        logger.error(f"خطأ في بناء prompt: {e}")
        return f"حلل إشارة {signal_data.get('symbol')} {signal_data.get('direction')}"


def analyze_signal_with_groq(signal_data, analysis_data=None):
    """تحليل إشارة بـ Groq"""
    if not ENABLE_GROQ_ANALYSIS or not groq_available or client is None:
        return None

    try:
        if GROQ_SEND_FULL_DATA:
            prompt = build_rich_prompt(signal_data, analysis_data)
        else:
            symbol = signal_data.get('symbol', 'UNKNOWN')
            direction = signal_data.get('direction', 'UNKNOWN')
            confidence = signal_data.get('confidence', 0)
            prompt = f"حلل {symbol} {direction} ثقة {confidence}%"

        messages = [
            {
                "role": "system",
                "content": "أنت محلل فني محترف في سوق العملات الرقمية. حلل بعمق وأجب بـ JSON صالح فقط."
            },
            {"role": "user", "content": prompt}
        ]

        response_content = None

        if _client_type in ("Groq", "Client"):
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1000,
                    top_p=0.9
                )
                response_content = response.choices[0].message.content
            except Exception as e:
                logger.warning(f"فشل: {e}")
                return None

        elif _client_type in ("http_client", "simple_http"):
            try:
                response = client.chat_completions_create(
                    model=GROQ_MODEL,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1000,
                    top_p=0.9
                )
                response_content = response['choices'][0]['message']['content']
            except Exception as e:
                logger.error(f"فشل HTTP: {e}")
                return None

        if response_content:
            logger.info(f"🧠 Groq raw: {response_content[:200]}...")
            result = parse_groq_response(response_content)

            if result:
                logger.info(f"✅ Groq {signal_data.get('symbol')}: {result['groq_recommendation']} ({result['groq_confidence']}%)")
                return result
            else:
                return {
                    'groq_recommendation': 'خطأ',
                    'groq_confidence': 0,
                    'groq_analysis': 'فشل التحليل',
                    'groq_reasoning': 'خطأ تقني',
                    'groq_risk_level': 'غير معروف'
                }

        return None

    except Exception as e:
        logger.error(f"❌ خطأ Groq: {e}")
        return None


def is_groq_available():
    return groq_available and ENABLE_GROQ_ANALYSIS and client is not None


def get_groq_status():
    return {
        'available': groq_available,
        'enabled': ENABLE_GROQ_ANALYSIS,
        'client_type': _client_type,
        'client_initialized': client is not None,
        'api_key_exists': bool(GROQ_API_KEY),
        'full_data_mode': GROQ_SEND_FULL_DATA
    }


enhance_signal_with_groq = analyze_signal_with_groq


if __name__ == "__main__":
    print("اختبار Groq:")
    print(get_groq_status())

    if is_groq_available():
        test_signal = {
            'symbol': 'BTCUSDT',
            'direction': 'BUY',
            'confidence': 75,
            'strength': 8,
            'entry_price': 45000,
            'timeframe_alignment': 7.5
        }
        result = analyze_signal_with_groq(test_signal)
        print(f"النتيجة: {result}")
