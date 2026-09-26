# -*- coding: utf-8 -*-
"""
groq_integration.py - الإصدار v6.1
🔧 OpenRouter كأساسي + Fallback إلى Gemini/Groq
"""

import logging
import json
import traceback
import requests
import re
import time

from config import (
    OPENROUTER_API_KEY, ENABLE_OPENROUTER_ANALYSIS,
    OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODELS, OPENROUTER_API_BASE_URL,
    GROQ_API_KEY, ENABLE_GROQ_ANALYSIS, GROQ_MODEL,
    GROQ_API_BASE_URL, GROQ_SEND_FULL_DATA,
    GEMINI_API_KEY, ENABLE_GEMINI_ANALYSIS, GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS, GEMINI_API_BASE_URL,
    AI_PROVIDER, AI_FALLBACK_ENABLED
)

logger = logging.getLogger("groq_integration")
logger.setLevel(logging.INFO)

openrouter_available = False
openrouter_working_model = None
groq_available = False
gemini_available = False
gemini_working_model = None

_groq_rate_limited_until = 0
_groq_daily_limit_reached = False


# ==================== OpenRouter ====================

def _try_init_openrouter():
    global openrouter_available, openrouter_working_model

    if not OPENROUTER_API_KEY:
        logger.info("ℹ️ OPENROUTER_API_KEY غير موجود")
        return False

    if not ENABLE_OPENROUTER_ANALYSIS:
        logger.info("ℹ️ OpenRouter معطل")
        return False

    try:
        url = f"{OPENROUTER_API_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mybot1.railway.app",
            "X-Title": "Trading Bot"
        }

        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5
        }

        response = requests.post(url, headers=headers, json=payload, timeout=20)

        if response.status_code == 200:
            openrouter_available = True
            openrouter_working_model = OPENROUTER_MODEL
            logger.info(f"✅ تهيئة OpenRouter: {OPENROUTER_MODEL}")
            return True
        else:
            logger.warning(f"⚠️ فشل OpenRouter: {response.status_code} - {response.text[:200]}")

            for model in OPENROUTER_FALLBACK_MODELS:
                if model == OPENROUTER_MODEL:
                    continue
                try:
                    payload["model"] = model
                    response = requests.post(url, headers=headers, json=payload, timeout=20)
                    if response.status_code == 200:
                        openrouter_available = True
                        openrouter_working_model = model
                        logger.info(f"✅ تهيئة OpenRouter: {model}")
                        return True
                except:
                    continue
            return False

    except Exception as e:
        logger.error(f"❌ فشل OpenRouter: {e}")
        return False


# ==================== Groq ====================

def _try_init_groq():
    global groq_available

    if not GROQ_API_KEY or not ENABLE_GROQ_ANALYSIS:
        return False

    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5
        }
        response = requests.post(
            f"{GROQ_API_BASE_URL}/chat/completions",
            headers=headers, json=payload, timeout=15
        )
        if response.status_code == 200:
            groq_available = True
            logger.info("✅ تهيئة Groq")
            return True
        else:
            logger.warning(f"⚠️ فشل Groq: {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"⚠️ فشل Groq: {e}")
        return False


# ==================== Gemini ====================

def _try_init_gemini():
    global gemini_available, gemini_working_model

    if not GEMINI_API_KEY or not ENABLE_GEMINI_ANALYSIS:
        return False

    models_to_try = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]

    for model in models_to_try:
        try:
            url = f"{GEMINI_API_BASE_URL}/models/{model}?key={GEMINI_API_KEY}"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                gemini_available = True
                gemini_working_model = model
                logger.info(f"✅ تهيئة Gemini: {model}")
                return True
        except:
            continue

    return False


# ==================== التهيئة ====================

logger.info("🔄 تهيئة OpenRouter...")
if _try_init_openrouter():
    logger.info("✅ OpenRouter جاهز (الأساسي)")
else:
    logger.warning("⚠️ OpenRouter غير متاح")

logger.info("🔄 تهيئة Groq...")
if _try_init_groq():
    logger.info("✅ Groq جاهز (احتياطي)")
else:
    logger.warning("⚠️ Groq غير متاح")

logger.info("🔄 تهيئة Gemini...")
if _try_init_gemini():
    logger.info(f"✅ Gemini جاهز (احتياطي): {gemini_working_model}")
else:
    logger.warning("⚠️ Gemini غير متاح")


# ==================== JSON Parsing ====================

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
    except:
        return None


def parse_ai_response(response_content, provider="unknown"):
    try:
        if not response_content:
            return None

        json_str = extract_json_from_response(response_content)

        if json_str:
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                json_str = re.sub(r':\s*thirty\s*', ': 30', json_str)
                json_str = re.sub(r':\s*forty\s*', ': 40', json_str)
                json_str = re.sub(r':\s*fifty\s*', ': 50', json_str)
                json_str = re.sub(r':\s*sixty\s*', ': 60', json_str)
                json_str = re.sub(r':\s*seventy\s*', ': 70', json_str)
                json_str = re.sub(r':\s*eighty\s*', ': 80', json_str)
                try:
                    data = json.loads(json_str)
                except:
                    return None

            required = ['recommendation', 'confidence', 'analysis']
            if all(k in data for k in required):
                result = {
                    'groq_recommendation': data['recommendation'],
                    'groq_confidence': data['confidence'],
                    'groq_analysis': data['analysis'],
                    'groq_reasoning': data.get('reasoning', ''),
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
        if "تأكيد" in response_content:
            recommendation = "تأكيد"
            confidence = 75
        elif "رفض" in response_content:
            recommendation = "رفض"
            confidence = 65

        match = re.search(r'ثقة[:\s]*(\d+)', response_content)
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
    except Exception as e:
        logger.error(f"خطأ في parse: {e}")
        return None


# ==================== Prompt ====================

def build_prompt(signal_data, analysis_data=None):
    try:
        symbol = signal_data.get('symbol', 'UNKNOWN')
        direction = signal_data.get('direction', 'UNKNOWN')
        confidence = signal_data.get('confidence', 0)
        entry_price = signal_data.get('entry_price', 0)
        analysis = analysis_data or signal_data.get('analysis', {})

        technical = analysis.get('technical_indicators', {})
        volume = analysis.get('volume_analysis', {})
        momentum = analysis.get('momentum', {})
        price_action = analysis.get('price_action', {})

        rsi = technical.get('rsi', 0)
        macd_trend = technical.get('macd_trend', 'محايد')
        vol_ratio = volume.get('volume_5m_ratio', 0)
        mom_dir = momentum.get('direction', 'محايد')
        mom_strength = momentum.get('strength', 0)
        candle_type = price_action.get('candle_type', 'غير معروف')
        body_ratio = price_action.get('body_ratio', 0)
        alignment = signal_data.get('timeframe_alignment', 0)

        prompt = f"""أنت محلل Scalp محترف. حلل الإشارة وأجب بـ JSON.

📊 {symbol} | {direction} | السعر: {entry_price}
RSI: {rsi:.1f} | MACD: {macd_trend} | الحجم: {vol_ratio:.2f}x
ترابط الفريمات: {alignment:.1f}/10
زخم: {mom_dir} ({mom_strength:.1f})
شمعة: {candle_type} (body={body_ratio:.2f})
ثقة النظام: {confidence:.1f}%

**قواعد الإجابة (Scalp Mode):**
- "تأكيد" إذا 50%+ من المعايير إيجابية
- "تحذير" عند تعارض واحد
- "رفض" فقط إذا: RSI>90 للشراء أو RSI<10 للبيع أو ترابط+MACD معاكسان

**أجب JSON فقط (بدون نص إضافي):**
{{
  "recommendation": "تأكيد" أو "تحذير" أو "رفض",
  "confidence": رقم من 0 إلى 100,
  "analysis": "تحليل موجز",
  "reasoning": "الأسباب",
  "risk_level": "عالي" أو "متوسط" أو "منخفض"
}}"""

        return prompt
    except Exception as e:
        logger.error(f"خطأ في build_prompt: {e}")
        return f"حلل {signal_data.get('symbol')} {signal_data.get('direction')}"


# ==================== OpenRouter Call ====================

def _call_openrouter(prompt):
    global openrouter_working_model

    try:
        url = f"{OPENROUTER_API_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://mybot1.railway.app",
            "X-Title": "Trading Bot"
        }

        models_to_try = [openrouter_working_model] if openrouter_working_model else []
        models_to_try += [m for m in OPENROUTER_FALLBACK_MODELS if m not in models_to_try]

        for model in models_to_try:
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "محلل فني Scalp. أجب JSON فقط."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 800
                }

                response = requests.post(url, headers=headers, json=payload, timeout=45)

                if response.status_code == 200:
                    data = response.json()
                    if 'choices' in data and data['choices']:
                        content = data['choices'][0]['message']['content']
                        openrouter_working_model = model
                        return content
                elif response.status_code == 429:
                    logger.warning(f"⏳ OpenRouter rate limit على {model}")
                    continue
                else:
                    logger.warning(f"⚠️ OpenRouter {model}: {response.status_code}")
                    continue

            except Exception as e:
                logger.warning(f"⚠️ خطأ OpenRouter {model}: {e}")
                continue

        return None

    except Exception as e:
        logger.error(f"❌ خطأ OpenRouter: {e}")
        return None


# ==================== Groq Call ====================

def _call_groq(prompt):
    global _groq_rate_limited_until, _groq_daily_limit_reached

    current_time = time.time()
    if _groq_daily_limit_reached and current_time < _groq_rate_limited_until:
        return None

    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "محلل فني Scalp. أجب JSON فقط."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 800
        }

        response = requests.post(
            f"{GROQ_API_BASE_URL}/chat/completions",
            headers=headers, json=payload, timeout=45
        )

        if response.status_code == 200:
            data = response.json()
            return data['choices'][0]['message']['content']
        elif response.status_code == 429:
            error_text = response.text
            match = re.search(r'try again in (\d+)m([\d.]+)s', error_text)
            if match:
                wait = int(match.group(1)) * 60 + float(match.group(2))
                _groq_rate_limited_until = time.time() + wait
                if "tokens per day" in error_text or "TPD" in error_text:
                    _groq_daily_limit_reached = True
                    logger.error(f"🚫 Groq: الحصة اليومية انتهت!")
            else:
                _groq_rate_limited_until = time.time() + 60
            return None
        else:
            return None

    except Exception as e:
        logger.warning(f"خطأ Groq: {e}")
        return None


# ==================== Gemini Call ====================

def _call_gemini(prompt):
    global gemini_working_model

    if not gemini_working_model:
        return None

    try:
        url = f"{GEMINI_API_BASE_URL}/models/{gemini_working_model}:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 800,
                "topP": 0.9
            }
        }

        response = requests.post(url, json=payload, timeout=45)

        if response.status_code != 200:
            return None

        data = response.json()
        if 'candidates' not in data or not data['candidates']:
            return None

        return data['candidates'][0]['content']['parts'][0].get('text', '')
    except Exception as e:
        logger.warning(f"خطأ Gemini: {e}")
        return None


# ==================== Main Function ====================

def analyze_signal_with_groq(signal_data, analysis_data=None):
    """
    الأولوية: OpenRouter → Gemini → Groq
    """
    try:
        prompt = build_prompt(signal_data, analysis_data)
        result = None

        # 1. OpenRouter
        if openrouter_available:
            logger.info(f"🧠 OpenRouter ({openrouter_working_model})...")
            content = _call_openrouter(prompt)
            if content:
                result = parse_ai_response(content, "openrouter")
                if result:
                    return result

        # 2. Gemini
        if AI_FALLBACK_ENABLED and gemini_available:
            logger.info("🔄 Fallback → Gemini...")
            content = _call_gemini(prompt)
            if content:
                result = parse_ai_response(content, "gemini")
                if result:
                    return result

        # 3. Groq
        if AI_FALLBACK_ENABLED and groq_available and not _groq_daily_limit_reached:
            logger.info("🔄 Fallback → Groq...")
            content = _call_groq(prompt)
            if content:
                result = parse_ai_response(content, "groq")
                if result:
                    return result

        logger.warning("⚠️ فشل كل مزودي AI")
        return None

    except Exception as e:
        logger.error(f"❌ خطأ AI: {e}")
        logger.error(traceback.format_exc())
        return None


def is_groq_available():
    groq_ok = groq_available and not _groq_daily_limit_reached
    return (openrouter_available or groq_ok or gemini_available)


def get_ai_status():
    return {
        'openrouter_available': openrouter_available,
        'openrouter_working_model': openrouter_working_model,
        'groq_available': groq_available,
        'groq_daily_limit_reached': _groq_daily_limit_reached,
        'gemini_available': gemini_available,
        'gemini_working_model': gemini_working_model,
        'ai_provider': AI_PROVIDER,
        'fallback_enabled': AI_FALLBACK_ENABLED,
        'active_provider': (
            'openrouter' if openrouter_available
            else 'gemini' if gemini_available
            else 'groq' if groq_available and not _groq_daily_limit_reached
            else 'none'
        )
    }


enhance_signal_with_groq = analyze_signal_with_groq


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("AI Status:")
    print(json.dumps(get_ai_status(), indent=2, ensure_ascii=False))