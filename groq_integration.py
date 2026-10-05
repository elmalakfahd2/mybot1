# -*- coding: utf-8 -*-
"""
groq_integration.py - الإصدار v8.4
🔧 التعديلات v8.2:
    - 🚫 HuggingFace معطل نهائياً: كان يرفض كل الإشارة بثقة منخفضة (0-60%) فيقتل كل شيء
    - ترتيب الاحتياطي الآن: Gemini → Groq → SambaNova → OpenRouter
    - (v8.1) Retry ذكي: 503 فقط (ليس 429) - Fallback فوري على 429
    - (v8.3) 🔥 Groq: إعادة محاولة تلقائية بعد انتهاء الحصة اليومية (كان يُستثني نهائياً
      حتى إعادة تشغيل البوت، فتنهار السلسلة كاملة عند انتهاء الحصة)
    - (v8.4) 🔥 SambaNova: تهيئة بمحاولتين + تشخيص سبب الفشل (مفتاح/نموذج/429)
      ومفعّل افتراضياً عبر متغيرات البيئة (فكرة من Claude — دمجتها هنا)

📅 آخر تعديل: 2026-10-01
"""

import logging
import json
import traceback
import requests
import re
import time

from config import (
    GEMINI_API_KEY, ENABLE_GEMINI_ANALYSIS, GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS, GEMINI_API_BASE_URL,
    GROQ_API_KEY, ENABLE_GROQ_ANALYSIS, GROQ_MODEL,
    GROQ_API_BASE_URL, GROQ_SEND_FULL_DATA,
    OPENROUTER_API_KEY, ENABLE_OPENROUTER_ANALYSIS,
    OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODELS, OPENROUTER_API_BASE_URL,
    SAMBANOVA_API_KEY, ENABLE_SAMBANOVA_ANALYSIS, SAMBANOVA_MODEL,
    SAMBANOVA_API_BASE_URL,
    HUGGINGFACE_API_KEY, ENABLE_HUGGINGFACE_ANALYSIS, HUGGINGFACE_MODEL,
    HUGGINGFACE_API_BASE_URL,
    AI_PROVIDER, AI_FALLBACK_ENABLED
)

logger = logging.getLogger("groq_integration")
logger.setLevel(logging.INFO)

# 🔥 حالة المزودين
gemini_available = False
gemini_working_model = None
groq_available = False
groq_working_model = None
sambanova_available = False
huggingface_available = False   # 🔥 v8.2: يبقى False دائماً (معطل)
openrouter_available = False
openrouter_working_model = None

# 🔥 Rate Limits
_groq_rate_limited_until = 0
_groq_daily_limit_reached = False
_sambanova_rate_limited_until = 0
_huggingface_rate_limited_until = 0


# ============================================================
# 1. تهيئة Gemini (الأساسي)
# ============================================================

def _try_init_gemini():
    global gemini_available, gemini_working_model

    if not GEMINI_API_KEY:
        logger.info("ℹ️ GEMINI_API_KEY غير موجود")
        return False

    if not ENABLE_GEMINI_ANALYSIS:
        logger.info("ℹ️ Gemini معطل")
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
            elif response.status_code == 404:
                logger.warning(f"⚠️ النموذج {model} غير متاح، تجربة التالي...")
                continue
            else:
                logger.warning(f"⚠️ فشل {model}: {response.status_code}")
                continue
        except Exception as e:
            logger.warning(f"⚠️ خطأ مع {model}: {e}")
            continue

    logger.error("❌ فشل كل نماذج Gemini")
    return False


# ============================================================
# 2. تهيئة HuggingFace - 🔥 v8.2: معطل نهائياً
# ============================================================

def _try_init_huggingface():
    """
    🔥 v8.2: HuggingFace معطل نهائياً.
    السبب: يرفض كل الإشارات بثقة منخفضة (0-60%) والكود كان يطبق فيتو قاتلاً
    على رفضه، فماتت كل الإشارات. النماذج الأخرى (Gemini/Groq/...) تبقى كما هي.
    """
    logger.info("🚫 HuggingFace معطل في v8.2 (كان يرفض كل الإشارات بثقة منخفضة فيقتل التداول)")
    return False


# ============================================================
# 3. تهيئة Groq (احتياطي 1)
# ============================================================

def _try_init_groq():
    global groq_available, groq_working_model

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
            groq_working_model = GROQ_MODEL
            logger.info(f"✅ تهيئة Groq: {GROQ_MODEL}")
            return True
        else:
            logger.warning(f"⚠️ فشل Groq: {response.status_code}")
            return False
    except Exception as e:
        logger.warning(f"⚠️ فشل Groq: {e}")
        return False


# ============================================================
# 4. تهيئة SambaNova (احتياطي 2 - معطل)
# ============================================================

def _try_init_sambanova():
    global sambanova_available

    if not ENABLE_SAMBANOVA_ANALYSIS:
        logger.warning("⚠️ SambaNova: معطل (ENABLE_SAMBANOVA_ANALYSIS=false)")
        return False
    if not SAMBANOVA_API_KEY:
        logger.warning("⚠️ SambaNova: متغير SAMBANOVA_API_KEY غير موجود في Variables")
        return False

    url = f"{SAMBANOVA_API_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {SAMBANOVA_API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": SAMBANOVA_MODEL,
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 5
    }

    for attempt in (1, 2):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20)
            code = response.status_code

            if code == 200:
                sambanova_available = True
                logger.info(f"✅ تهيئة SambaNova: {SAMBANOVA_MODEL}")
                return True
            if code == 429:
                # المفتاح سليم لكن الحصة مؤقتاً ممتلئة → نفعّله، و _call_sambanova يتعامل مع 429
                sambanova_available = True
                logger.warning("⚠️ SambaNova: 429 (حد مؤقت) - تم التفعيل والمحاولة لاحقاً")
                return True
            if code in (401, 403):
                logger.error(f"❌ SambaNova: المفتاح مرفوض ({code}) - تحقق من SAMBANOVA_API_KEY")
                return False
            if code == 404 or code == 400:
                logger.error(f"❌ SambaNova: النموذج/الطلب غير صحيح ({code}) "
                             f"model={SAMBANOVA_MODEL} - {response.text[:150]}")
                return False
            logger.warning(f"⚠️ SambaNova: HTTP {code} (محاولة {attempt}) - {response.text[:120]}")
        except Exception as e:
            logger.warning(f"⚠️ SambaNova: خطأ اتصال (محاولة {attempt}): {e}")
        time.sleep(2)

    return False

# ============================================================
# 5. تهيئة OpenRouter (احتياطي 3)
# ============================================================

def _try_init_openrouter():
    global openrouter_available, openrouter_working_model

    if not OPENROUTER_API_KEY or not ENABLE_OPENROUTER_ANALYSIS:
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
        return False


# ============================================================
# التهيئة الشاملة
# ============================================================

logger.info("=" * 60)
logger.info("🔄 تهيئة مزودي AI...")

if _try_init_gemini():
    logger.info("✅ Gemini جاهز (الأساسي)")
else:
    logger.warning("⚠️ Gemini غير متاح")

if _try_init_huggingface():
    logger.info("✅ HuggingFace جاهز (احتياطي 1)")
else:
    logger.info("ℹ️ HuggingFace معطل (v8.2)")

if _try_init_groq():
    logger.info("✅ Groq جاهز (احتياطي 1)")
else:
    logger.warning("⚠️ Groq غير متاح")

if _try_init_sambanova():
    logger.info("✅ SambaNova جاهز (احتياطي 2)")
else:
    logger.warning("⚠️ SambaNova غير متاح")

if _try_init_openrouter():
    logger.info("✅ OpenRouter جاهز (احتياطي 3)")
else:
    logger.warning("⚠️ OpenRouter غير متاح")

logger.info("=" * 60)


# ============================================================
# استخراج JSON من الاستجابة
# ============================================================

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


# ============================================================
# بناء الـ Prompt
# ============================================================

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

        # 🔥 v5.7: سياق السوق وسجل البوت (يبنيه adaptive_rules)
        ai_context = signal_data.get('ai_context', '') or ''
        context_block = f"\n📚 سياق السوق وسجل البوت:\n{ai_context}\n" if ai_context else ""

        prompt = f"""أنت مدير مخاطر لبوت تداول عقود آجلة برافعة 15x وSL قريب من 1.3%.
أي إشارة خاسرة تكلف البوت نحو 2$ بينما الربح المتوقع أقل. مهمتك حماية رأس المال: لا تؤكد الإشارة إلا إذا كانت الأدلة قوية فعلاً. أجب بـ JSON.

📊 {symbol} | {direction} | السعر: {entry_price}
RSI: {rsi:.1f} | MACD: {macd_trend} | الحجم: {vol_ratio:.2f}x
ترابط الفريمات: {alignment:.1f}/10
زخم: {mom_dir} ({mom_strength:.1f})
شمعة: {candle_type} (body={body_ratio:.2f})
ثقة النظام: {confidence:.1f}%
{context_block}
**قواعد الإجابة:**
- "تأكيد" فقط إذا المؤشرات متوافقة مع الاتجاه ولا يوجد تحذير في السياق أعلاه
- "تحذير" عند تعارض واحد أو عندما يكون أداء البوت أو العملة الأخير سيئاً في نفس الاتجاه
- "رفض" إذا: RSI>85 للشراء أو RSI<15 للبيع، أو ترابط+MACD معاكسان، أو الإشارة عكس اتجاه السوق القوي (BTC)، أو خسرت العملة مرتين أو أكثر في نفس الاتجاه مؤخراً
- اذكر في reasoning السبب الأهم في جملة واحدة

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


# ============================================================
# دوال الاستدعاء - كل مزود
# ============================================================

def _call_gemini(prompt, max_retries=2):
    """
    🔥 v8.1:
    - Retry فقط على 503 (مشغول)
    - عدم Retry على 429 (rate limit) - فوري للـ fallback
    """
    global gemini_working_model
    if not gemini_working_model:
        return None

    for attempt in range(max_retries):
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

            # 🔥 429 = rate limit → Fallback فوري (لا retry)
            if response.status_code == 429:
                logger.warning(f"⚠️ Gemini 429 - rate limit (fallback فوري)")
                time.sleep(2)
                return None

            # 🔥 503 = مشغول → retry
            if response.status_code == 503:
                if attempt < max_retries - 1:
                    wait = 3 * (attempt + 1)
                    logger.warning(f"⚠️ Gemini 503 - محاولة {attempt+1}/{max_retries} - انتظار {wait}s")
                    time.sleep(wait)
                    continue
                logger.warning(f"⚠️ Gemini 503 - فشل نهائي")
                return None

            if response.status_code != 200:
                logger.warning(f"⚠️ Gemini {response.status_code} - فشل")
                return None

            data = response.json()
            if 'candidates' not in data or not data['candidates']:
                return None

            text = data['candidates'][0]['content']['parts'][0].get('text', '')
            if not text:
                return None

            logger.info(f"✅ Gemini نجح (محاولة {attempt+1})")
            return text

        except requests.exceptions.Timeout:
            logger.warning(f"⚠️ Gemini timeout - محاولة {attempt+1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            logger.warning(f"خطأ Gemini: {e}")
            return None

    return None


def _call_huggingface(prompt, max_retries=3):
    """🔥 v8.2: معطل نهائياً - لا يُستدعى أبداً من السلسلة"""
    logger.debug("🚫 HuggingFace معطل (v8.2)")
    return None


def _call_groq(prompt, max_retries=2):
    """🔥 استدعاء Groq (احتياطي 1)"""
    global _groq_rate_limited_until, _groq_daily_limit_reached

    current_time = time.time()
    if _groq_daily_limit_reached and current_time < _groq_rate_limited_until:
        remaining = int((_groq_rate_limited_until - current_time) / 3600)
        logger.info(f"⏳ Groq: الحصة اليومية مستنفدة - إعادة المحاولة بعد ~{remaining} ساعة")
        return None
    if _groq_daily_limit_reached and current_time >= _groq_rate_limited_until:
        # 🔥 v8.3: انتهت مهلة الانتظار - جرّب Groq من جديد
        _groq_daily_limit_reached = False
        logger.info("🔄 Groq: انتهت مهلة الانتظار - إعادة تفعيل المحاولة")

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
            logger.info(f"✅ Groq نجح")
            return data['choices'][0]['message']['content']
        elif response.status_code == 429:
            error_text = response.text
            match = re.search(r'try again in (\d+)m([\d.]+)s', error_text)
            if match:
                wait = int(match.group(1)) * 60 + float(match.group(2))
                _groq_rate_limited_until = time.time() + wait
                if "tokens per day" in error_text or "TPD" in error_text:
                    _groq_daily_limit_reached = True
                    # 🔥 v8.3: انتظر ساعتين فقط ثم أعد المحاولة (بدل الاستثناء الدائم)
                    _groq_rate_limited_until = time.time() + 2 * 3600
                    logger.error(f"🚫 Groq: الحصة اليومية انتهت! إعادة المحاولة بعد ساعتين")
            else:
                _groq_rate_limited_until = time.time() + 60
            return None
        else:
            return None
    except Exception as e:
        logger.warning(f"خطأ Groq: {e}")
        return None


def _call_sambanova(prompt):
    """SambaNova (احتياطي 2)"""
    global _sambanova_rate_limited_until
    if time.time() < _sambanova_rate_limited_until or not sambanova_available:
        return None

    try:
        url = f"{SAMBANOVA_API_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {SAMBANOVA_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": SAMBANOVA_MODEL,
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
            return data['choices'][0]['message']['content']
        elif response.status_code == 429:
            _sambanova_rate_limited_until = time.time() + 60
            return None
        return None
    except:
        return None


def _call_openrouter(prompt):
    """OpenRouter (احتياطي 3)"""
    global openrouter_working_model
    if not openrouter_available:
        return None

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
                    continue
                else:
                    continue
            except:
                continue
        return None
    except:
        return None


# ============================================================
# 🔥 الدالة الرئيسية - الترتيب الجديد (v8.2: بدون HuggingFace)
# ============================================================

def analyze_signal_with_groq(signal_data, analysis_data=None):
    """
    🔥 التسلسل الذكي (v8.2):
    1. Gemini (الأساسي - retry ذكي)
    2. Groq (احتياطي 1 - محمي بالحصص)
    3. SambaNova (احتياطي 2)
    4. OpenRouter (احتياطي 3 - أخير)
    (HuggingFace أُزيل في v8.2: كان يرفض كل الإشارات بثقة منخفضة)
    """
    try:
        prompt = build_prompt(signal_data, analysis_data)
        result = None

        # ==================== 1. Gemini (الأساسي) ====================
        if gemini_available:
            logger.info("🧠 استخدام Gemini (أساسي)...")
            content = _call_gemini(prompt, max_retries=2)
            if content:
                result = parse_ai_response(content, "gemini")
                if result:
                    return result
            logger.warning("⚠️ Gemini فشل - الانتقال إلى المزود الاحتياطي التالي")

        # ==================== 2. Groq (احتياطي 1) ====================
        if AI_FALLBACK_ENABLED and groq_available and not _groq_daily_limit_reached:
            logger.info("🔄 Fallback → Groq...")
            content = _call_groq(prompt, max_retries=1)
            if content:
                result = parse_ai_response(content, "groq")
                if result:
                    return result

        # ==================== 3. SambaNova (احتياطي 2) ====================
        if AI_FALLBACK_ENABLED and sambanova_available:
            logger.info("🔄 Fallback → SambaNova...")
            content = _call_sambanova(prompt)
            if content:
                result = parse_ai_response(content, "sambanova")
                if result:
                    return result

        # ==================== 4. OpenRouter (احتياطي 3) ====================
        if AI_FALLBACK_ENABLED and openrouter_available:
            logger.info("🔄 Fallback → OpenRouter...")
            content = _call_openrouter(prompt)
            if content:
                result = parse_ai_response(content, "openrouter")
                if result:
                    return result

        logger.error("❌ فشل كل مزودي AI")
        return None

    except Exception as e:
        logger.error(f"❌ خطأ AI: {e}")
        logger.error(traceback.format_exc())
        return None


def is_groq_available():
    return (
        gemini_available or
        (groq_available and not _groq_daily_limit_reached) or
        sambanova_available or
        openrouter_available
    )


def get_ai_status():
    return {
        'gemini_available': gemini_available,
        'gemini_working_model': gemini_working_model,
        'huggingface_available': huggingface_available,
        'groq_available': groq_available,
        'groq_daily_limit_reached': _groq_daily_limit_reached,
        'sambanova_available': sambanova_available,
        'openrouter_available': openrouter_available,
        'openrouter_working_model': openrouter_working_model,
        'ai_provider': AI_PROVIDER,
        'fallback_enabled': AI_FALLBACK_ENABLED,
        'active_provider': (
            'gemini' if gemini_available
            else 'groq' if groq_available and not _groq_daily_limit_reached
            else 'sambanova' if sambanova_available
            else 'openrouter' if openrouter_available
            else 'none'
        )
    }


enhance_signal_with_groq = analyze_signal_with_groq


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("AI Status:")
    print(json.dumps(get_ai_status(), indent=2, ensure_ascii=False))
