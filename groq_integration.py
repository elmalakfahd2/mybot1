# -*- coding: utf-8 -*-
"""
groq_integration.py - الإصدار v5.4 (Scalp Mode)
🔧 التعديلات v5.4:
   - 🔥 Prompt محسّن لقبول الإشارات مع TP ضيق
   - 🔥 RSI متشبع مسموح مع تحذير
   - 🔥 "تأكيد" أكثر تكراراً
"""

import logging
import json
import traceback
import requests
import re
import os

from config import (
    GROQ_API_KEY, ENABLE_GROQ_ANALYSIS, GROQ_MODEL,
    GROQ_API_BASE_URL, GROQ_SEND_FULL_DATA,
    GEMINI_API_KEY, ENABLE_GEMINI_ANALYSIS, GEMINI_MODEL,
    GEMINI_API_BASE_URL, AI_PROVIDER, AI_FALLBACK_ENABLED,
    RSI_BUY_HARD_REJECT, RSI_SELL_HARD_REJECT,
    RSI_BUY_WARNING, RSI_SELL_WARNING
)

logger = logging.getLogger("groq_integration")
logger.setLevel(logging.INFO)

groq_available = False
gemini_available = False
client = None
_client_type = None


# ==================== تهيئة Groq ====================

def _try_init_groq_library():
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
    global groq_available, client, _client_type

    if not GROQ_API_KEY:
        return False

    class GroqHTTPClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.base_url = GROQ_API_BASE_URL
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
            f"{GROQ_API_BASE_URL}/chat/completions",
            headers=test_client.headers,
            json=test_payload,
            timeout=15
        )

        if test_response.status_code == 200:
            client = test_client
            _client_type = "http_client"
            groq_available = True
            logger.info("✅ تهيئة Groq HTTP")
            return True
        else:
            logger.error(f"فشل اختبار Groq: {test_response.status_code}")
            return False

    except Exception as e:
        logger.error(f"فشل Groq HTTP: {e}")
        return False


# ==================== تهيئة Gemini ====================

def _try_init_gemini():
    global gemini_available

    if not GEMINI_API_KEY:
        logger.info("ℹ️ GEMINI_API_KEY غير موجود")
        return False

    if not ENABLE_GEMINI_ANALYSIS:
        logger.info("ℹ️ Gemini معطل")
        return False

    try:
        url = f"{GEMINI_API_BASE_URL}/models/{GEMINI_MODEL}?key={GEMINI_API_KEY}"
        response = requests.get(url, timeout=15)

        if response.status_code == 200:
            gemini_available = True
            logger.info("✅ تهيئة Gemini")
            return True
        else:
            logger.warning(f"⚠️ فشل اختبار Gemini: {response.status_code}")
            return False

    except Exception as e:
        logger.warning(f"⚠️ فشل Gemini: {e}")
        return False


# ==================== التهيئة ====================

if ENABLE_GROQ_ANALYSIS and GROQ_API_KEY:
    logger.info("🔄 تهيئة Groq...")
    if not _try_init_groq_library():
        if not _init_groq_http_fallback():
            logger.error("❌ فشل كل محاولات Groq")
else:
    if not ENABLE_GROQ_ANALYSIS:
        logger.info("ℹ️ Groq معطل")
    if not GROQ_API_KEY:
        logger.warning("⚠️ GROQ_API_KEY مفقود")

logger.info("🔄 تهيئة Gemini...")
if _try_init_gemini():
    logger.info("✅ Gemini جاهز")
else:
    logger.warning("⚠️ Gemini غير متاح - سيتم استخدام Groq فقط")


# ==================== استخراج JSON ====================

def extract_json_from_response(response_content):
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


def parse_ai_response(response_content, provider="groq"):
    """تحليل استجابة AI"""
    try:
        if not response_content:
            return None

        json_str = extract_json_from_response(response_content)

        if json_str:
            data = json.loads(json_str)

            required = ['recommendation', 'confidence', 'analysis']
            if all(k in data for k in required):
                result = {
                    'groq_recommendation': data['recommendation'],
                    'groq_confidence': data['confidence'],
                    'groq_analysis': data['analysis'],
                    'groq_reasoning': data.get('reasoning', 'لا توجد أسباب'),
                    'groq_risk_level': data.get('risk_level', 'متوسط'),
                    'ai_provider': provider
                }
                logger.info(f"✅ AI ({provider}): {result['groq_recommendation']} ({result['groq_confidence']}%)")
                return result
            else:
                return {
                    'groq_recommendation': data.get('recommendation', 'تحذير'),
                    'groq_confidence': data.get('confidence', 50),
                    'groq_analysis': data.get('analysis', response_content[:300]),
                    'groq_reasoning': data.get('reasoning', ''),
                    'groq_risk_level': data.get('risk_level', 'متوسط'),
                    'ai_provider': provider
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
            'groq_risk_level': 'متوسط',
            'ai_provider': provider
        }

    except json.JSONDecodeError as e:
        logger.error(f"خطأ JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"خطأ: {e}")
        return None


# ==================== بناء الـ Prompt (Scalp Mode) ====================

def build_rich_prompt(signal_data, analysis_data=None):
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
        body_ratio = price_action.get('body_ratio', 0)

        alignment = signal_data.get('timeframe_alignment', 0)
        volatility = technical.get('volatility', 'غير معروف')

        prompt = f"""أنت محلل فني خبير في **Scalp Trading** (خطف أرباح صغيرة سريعة). مهمتك **تأكيد الإشارات الجيدة بسرعة**.

📊 **بيانات الإشارة:**
- العملة: {symbol}
- الاتجاه: {direction}
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
- قوة الجسم: {body_strength} (body_ratio={body_ratio:.2f})

---

**⚠️ قواعد الإجابة (Scalp Mode - مهم جداً):**

**هذه استراتيجية Scalp - نهدف لأرباح صغيرة سريعة (0.8% للـ TP1) قبل الانعكاس المحتمل.**

1. **"تأكيد"** إذا كان **50% أو أكثر** من المعايير إيجابية:
   - ترابط الفريمات >= 5/10
   - MACD متوافق مع الاتجاه
   - الحجم >= 0.8x
   - **حتى لو RSI متشبع (75-88)، هذا مقبول** لأن TP ضيق

2. **"تحذير"** فقط عند تعارض حقيقي واحد:
   - مثال: كل المؤشرات معاكسة
   - مثال: RSI > 88 (خطر انعكاس فوري)

3. **"رفض" فقط عند خطر واضح جداً:**
   - RSI >= 90 (تشبع عنيف جداً)
   - MACD معاكس + ترابط معاكس
   - السوق هابط قوي وأنت تشتري

4. **⚠️ مهم جداً في Scalp Mode:**
   - **التردد الزائد = فقدان الفرص**
   - **إذا 3 من 4 معايير إيجابية → "تأكيد"**
   - **RSI 70-85 مقبول** مع TP ضيق (0.8%)
   - **RSI 85-90 مقبول** مع TP ضيق جداً (0.5%)
   - **RSI >= 90 → "رفض"** إجباري

**المطلوب:**
1. القرار: تأكيد / تحذير / رفض
2. الثقة: 0-100
3. تحليل موجز (2-3 جمل)
4. الأسباب (3-4 نقاط)
5. المخاطرة: عالي / متوسط / منخفض

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


# ==================== Groq Call ====================

def _call_groq(prompt, messages):
    try:
        response_content = None

        if _client_type in ("Groq", "Client"):
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                top_p=0.9
            )
            response_content = response.choices[0].message.content

        elif _client_type in ("http_client", "simple_http"):
            response = client.chat_completions_create(
                model=GROQ_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=1000,
                top_p=0.9
            )
            response_content = response['choices'][0]['message']['content']

        return response_content

    except Exception as e:
        logger.warning(f"فشل Groq: {e}")
        return None


# ==================== Gemini Call ====================

def _call_gemini(prompt):
    try:
        url = f"{GEMINI_API_BASE_URL}/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1000,
                "topP": 0.9,
                "responseMimeType": "application/json"
            }
        }

        response = requests.post(url, json=payload, timeout=45)

        if response.status_code != 200:
            logger.warning(f"فشل Gemini: {response.status_code} - {response.text[:200]}")
            return None

        data = response.json()

        if 'candidates' not in data or not data['candidates']:
            logger.warning("لا يوجد candidates في Gemini")
            return None

        candidate = data['candidates'][0]
        if 'content' not in candidate or 'parts' not in candidate['content']:
            logger.warning("لا يوجد content في Gemini")
            return None

        text = candidate['content']['parts'][0].get('text', '')
        return text

    except Exception as e:
        logger.warning(f"خطأ Gemini: {e}")
        return None


# ==================== الدالة الرئيسية ====================

def analyze_signal_with_groq(signal_data, analysis_data=None):
    """تحليل إشارة بـ AI"""
    try:
        if GROQ_SEND_FULL_DATA:
            prompt = build_rich_prompt(signal_data, analysis_data)
        else:
            symbol = signal_data.get('symbol', 'UNKNOWN')
            direction = signal_data.get('direction', 'UNKNOWN')
            confidence = signal_data.get('confidence', 0)
            prompt = f"حلل {symbol} {direction} ثقة {confidence}%"

        use_gemini_first = (AI_PROVIDER == "gemini")
        use_auto = (AI_PROVIDER == "auto")

        result = None

        if use_gemini_first or (use_auto and gemini_available and not groq_available):
            if gemini_available:
                logger.info("🧠 استخدام Gemini...")
                response_content = _call_gemini(prompt)
                if response_content:
                    result = parse_ai_response(response_content, "gemini")
                    if result:
                        return result

        if groq_available:
            logger.info("🧠 استخدام Groq...")
            messages = [
                {
                    "role": "system",
                    "content": "أنت محلل فني محترف في Scalp Trading. مهمتك تأكيد الإشارات الجيدة بسرعة. RSI 70-88 مقبول إذا TP ضيق. أجب بـ JSON فقط."
                },
                {"role": "user", "content": prompt}
            ]

            response_content = _call_groq(prompt, messages)
            if response_content:
                logger.info(f"🧠 Groq raw: {response_content[:200]}...")
                result = parse_ai_response(response_content, "groq")
                if result:
                    return result

        if AI_FALLBACK_ENABLED:
            if not use_gemini_first and gemini_available:
                logger.info("🔄 Fallback → Gemini...")
                response_content = _call_gemini(prompt)
                if response_content:
                    result = parse_ai_response(response_content, "gemini")
                    if result:
                        return result

        logger.warning("⚠️ فشل كل مزودي AI")
        return None

    except Exception as e:
        logger.error(f"❌ خطأ AI: {e}")
        logger.error(traceback.format_exc())
        return None


def is_groq_available():
    return (groq_available or gemini_available)


def get_ai_status():
    return {
        'groq_available': groq_available,
        'gemini_available': gemini_available,
        'groq_client_type': _client_type,
        'groq_api_key_exists': bool(GROQ_API_KEY),
        'gemini_api_key_exists': bool(GEMINI_API_KEY),
        'ai_provider': AI_PROVIDER,
        'fallback_enabled': AI_FALLBACK_ENABLED,
        'active_provider': 'gemini' if (AI_PROVIDER == "gemini" or (AI_PROVIDER == "auto" and not groq_available and gemini_available)) else 'groq' if groq_available else 'none'
    }


enhance_signal_with_groq = analyze_signal_with_groq


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("اختبار AI:")
    print(get_ai_status())

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