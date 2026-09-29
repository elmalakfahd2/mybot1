# -*- coding: utf-8 -*-
"""
groq_integration.py - الإصدار v9.0
🔧 التعديلات v9.0:
    - 🔥 build_prompt مع context كامل (تاريخ الصفقات + BTC + السوق)
    - 🔥 قواعد صارمة للرفض
    - Retry ذكي: 503 فقط
    - ترتيب: Gemini → HuggingFace → Groq → SambaNova → OpenRouter

📅 آخر تعديل: 2026-09-29
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
huggingface_available = False
openrouter_available = False
openrouter_working_model = None

_groq_rate_limited_until = 0
_groq_daily_limit_reached = False
_sambanova_rate_limited_until = 0
_huggingface_rate_limited_until = 0


# ============================================================
# تهيئة المزودين
# ============================================================

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
            elif response.status_code == 404:
                continue
            else:
                continue
        except Exception:
            continue

    logger.error("❌ فشل كل نماذج Gemini")
    return False


def _try_init_huggingface():
    global huggingface_available

    if not HUGGINGFACE_API_KEY or not ENABLE_HUGGINGFACE_ANALYSIS:
        return False

    try:
        url = f"{HUGGINGFACE_API_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": HUGGINGFACE_MODEL,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code == 200:
            huggingface_available = True
            logger.info(f"✅ تهيئة HuggingFace: {HUGGINGFACE_MODEL}")
            return True
        return False
    except Exception:
        return False


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
        return False
    except Exception:
        return False


def _try_init_sambanova():
    global sambanova_available

    if not SAMBANOVA_API_KEY or not ENABLE_SAMBANOVA_ANALYSIS:
        return False

    try:
        url = f"{SAMBANOVA_API_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {SAMBANOVA_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": SAMBANOVA_MODEL,
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": 5
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)

        if response.status_code == 200:
            sambanova_available = True
            logger.info(f"✅ تهيئة SambaNova: {SAMBANOVA_MODEL}")
            return True
        return False
    except Exception:
        return False


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
        return False
    except Exception:
        return False


# التهيئة الشاملة
logger.info("=" * 60)
logger.info("🔄 تهيئة مزودي AI...")

if _try_init_gemini():
    logger.info("✅ Gemini جاهز (الأساسي)")
else:
    logger.warning("⚠️ Gemini غير متاح")

if _try_init_huggingface():
    logger.info("✅ HuggingFace جاهز (احتياطي 1)")
else:
    logger.warning("⚠️ HuggingFace غير متاح")

if _try_init_groq():
    logger.info("✅ Groq جاهز (احتياطي 2)")
else:
    logger.warning("⚠️ Groq غير متاح")

if _try_init_sambanova():
    logger.info("✅ SambaNova جاهز (احتياطي 3)")
else:
    logger.warning("⚠️ SambaNova غير متاح")

if _try_init_openrouter():
    logger.info("✅ OpenRouter جاهز (احتياطي 4)")
else:
    logger.warning("⚠️ OpenRouter غير متاح")

logger.info("=" * 60)


# ============================================================
# استخراج JSON
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

        # استخراج نصي احتياطي
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
# 🔥 build_prompt مع context كامل (جديد v9.0)
# ============================================================

def build_prompt(signal_data, analysis_data=None):
    """
    🔥 v9.0: Prompt مع context كامل:
    - تاريخ الصفقات السابقة للعملة
    - حالة BTC
    - حالة السوق العامة
    - قواعد صارمة للرفض
    """
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

        # 🔥 1. تاريخ العملة
        symbol_history = ""
        try:
            import trade_memory as memory
            recent = memory.get_symbol_history(symbol, limit=5)
            if recent:
                wins = sum(1 for t in recent if t.get('is_win', False))
                losses = len(recent) - wins
                total_pnl = sum(t.get('pnl', 0) for t in recent)
                symbol_history = f"""
📊 <b>تاريخ {symbol}</b> (آخر {len(recent)} صفقات):
   • رابحة: {wins} | خاسرة: {losses}
   • صافي PnL: {total_pnl:+.2f}$"""
            else:
                symbol_history = f"\n📊 <b>تاريخ {symbol}:</b> لا يوجد (عملة جديدة)"
        except:
            pass

        # 🔥 2. حالة BTC
        btc_context = ""
        try:
            import core_functions as core
            btc_price = core.get_price("BTCUSDT")
            if btc_price:
                btc_context = f"\n💰 <b>BTC:</b> {btc_price:,.0f}$"
        except:
            pass

        # 🔥 3. حالة السوق
        market_context = ""
        try:
            from market_regime import MarketRegime
            regime = MarketRegime.get_regime()
            market_context = f"\n🌊 <b>السوق:</b> {regime.get('regime_ar', 'غير معروف')} - {regime.get('recommendation', '')}"
        except:
            pass

        prompt = f"""أنت محلل Scalp محترف. حلل الإشارة التالية بدقة:

🎯 <b>الإشارة:</b>
   • العملة: {symbol}
   • الاتجاه: {direction}
   • السعر: {entry_price}

📊 <b>المؤشرات:</b>
   • RSI: {rsi:.1f}
   • MACD: {macd_trend}
   • الحجم: {vol_ratio:.2f}x
   • الترابط: {alignment:.1f}/10
   • الزخم: {mom_dir} ({mom_strength:.1f})
   • الشمعة: {candle_type} (body={body_ratio:.2f})
   • ثقة النظام: {confidence:.1f}%

{symbol_history}{btc_context}{market_context}

⚠️ <b>قواعد صارمة (اتبعها بدقة):</b>

❌ <b>ارفض فوراً إذا:</b>
   1. RSI > 68 (تشبع شرائي) للشراء
   2. RSI < 32 (تشبع بيعي) للبيع
   3. MACD يعاكس الاتجاه
   4. الترابط < 5/10
   5. العملة لديها 2+ خسائر في آخر 5 صفقات

✅ <b>تأكيد فقط إذا (كل الشروط):</b>
   1. RSI في النطاق المثالي (40-65)
   2. الحجم ≥ 1.5x
   3. الترابط ≥ 7/10
   4. MACD متوافق مع الاتجاه
   5. تاريخ العملة إيجابي أو محايد

⚠️ <b>تحذير إذا:</b>
   - شرط واحد ضعيف
   - التاريخ مختلط
   - السوق متذبذب

**أجب JSON فقط (بدون نص إضافي):**
{{
  "recommendation": "تأكيد" أو "تحذير" أو "رفض",
  "confidence": رقم من 0 إلى 100,
  "analysis": "تحليل موجز جداً (سطر واحد)",
  "reasoning": "سبب قرارك (سطر واحد)",
  "risk_level": "عالي" أو "متوسط" أو "منخفض"
}}"""

        return prompt
    except Exception as e:
        logger.error(f"خطأ في build_prompt: {e}")
        return f"حلل {signal_data.get('symbol')} {signal_data.get('direction')}"


# ============================================================
# دوال الاستدعاء
# ============================================================

def _call_gemini(prompt, max_retries=2):
    """Retry فقط على 503"""
    global gemini_working_model
    if not gemini_working_model:
        return None

    for attempt in range(max_retries):
        try:
            url = f"{GEMINI_API_BASE_URL}/models/{gemini_working_model}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 800,
                    "topP": 0.9
                }
            }

            response = requests.post(url, json=payload, timeout=45)

            if response.status_code == 429:
                logger.warning(f"⚠️ Gemini 429 - rate limit (fallback فوري)")
                time.sleep(2)
                return None

            if response.status_code == 503:
                if attempt < max_retries - 1:
                    wait = 3 * (attempt + 1)
                    logger.warning(f"⚠️ Gemini 503 - محاولة {attempt+1}/{max_retries} - انتظار {wait}s")
                    time.sleep(wait)
                    continue
                return None

            if response.status_code != 200:
                logger.warning(f"⚠️ Gemini {response.status_code}")
                return None

            data = response.json()
            if 'candidates' not in data or not data['candidates']:
                return None

            text = data['candidates'][0]['content']['parts'][0].get('text', '')
            if text:
                logger.info(f"✅ Gemini نجح (محاولة {attempt+1})")
                return text
            return None

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None
        except Exception as e:
            logger.warning(f"خطأ Gemini: {e}")
            return None

    return None


def _call_huggingface(prompt, max_retries=3):
    global _huggingface_rate_limited_until

    if time.time() < _huggingface_rate_limited_until or not huggingface_available:
        return None

    for attempt in range(max_retries):
        try:
            url = f"{HUGGINGFACE_API_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": HUGGINGFACE_MODEL,
                "messages": [
                    {"role": "system", "content": "محلل فني Scalp. أجب JSON فقط."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 800
            }
            response = requests.post(url, headers=headers, json=payload, timeout=45)

            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and data['choices']:
                    logger.info(f"✅ HuggingFace نجح")
                    return data['choices'][0]['message']['content']
                return None
            elif response.status_code == 429:
                _huggingface_rate_limited_until = time.time() + 60
                logger.warning("⏳ HuggingFace rate limit")
                return None
            elif response.status_code == 503:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                return None
            elif response.status_code == 402:
                logger.error("🚫 HuggingFace: نفد الرصيد")
                _huggingface_rate_limited_until = time.time() + 86400
                return None
            else:
                logger.warning(f"⚠️ HuggingFace: {response.status_code}")
                return None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None

    return None


def _call_groq(prompt, max_retries=2):
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
            "temperature": 0.2,
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
                    logger.error(f"🚫 Groq: الحصة اليومية انتهت!")
            else:
                _groq_rate_limited_until = time.time() + 60
            return None
        return None
    except Exception as e:
        logger.warning(f"خطأ Groq: {e}")
        return None


def _call_sambanova(prompt):
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
            "temperature": 0.2,
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
                    "temperature": 0.2,
                    "max_tokens": 800
                }
                response = requests.post(url, headers=headers, json=payload, timeout=45)

                if response.status_code == 200:
                    data = response.json()
                    if 'choices' in data and data['choices']:
                        content = data['choices'][0]['message']['content']
                        openrouter_working_model = model
                        return content
            except:
                continue
        return None
    except:
        return None


# ============================================================
# الدالة الرئيسية
# ============================================================

def analyze_signal_with_groq(signal_data, analysis_data=None):
    """
    🔥 التسلسل: Gemini → HuggingFace → Groq → SambaNova → OpenRouter
    """
    try:
        prompt = build_prompt(signal_data, analysis_data)
        result = None

        # 1. Gemini
        if gemini_available:
            logger.info("🧠 استخدام Gemini (أساسي)...")
            content = _call_gemini(prompt, max_retries=2)
            if content:
                result = parse_ai_response(content, "gemini")
                if result:
                    return result
            logger.warning("⚠️ Gemini فشل - التبديل إلى HuggingFace")

        # 2. HuggingFace
        if AI_FALLBACK_ENABLED and huggingface_available:
            logger.info("🔄 Fallback → HuggingFace...")
            content = _call_huggingface(prompt, max_retries=3)
            if content:
                result = parse_ai_response(content, "huggingface")
                if result:
                    return result

        # 3. Groq
        if AI_FALLBACK_ENABLED and groq_available and not _groq_daily_limit_reached:
            logger.info("🔄 Fallback → Groq...")
            content = _call_groq(prompt, max_retries=1)
            if content:
                result = parse_ai_response(content, "groq")
                if result:
                    return result

        # 4. SambaNova
        if AI_FALLBACK_ENABLED and sambanova_available:
            logger.info("🔄 Fallback → SambaNova...")
            content = _call_sambanova(prompt)
            if content:
                result = parse_ai_response(content, "sambanova")
                if result:
                    return result

        # 5. OpenRouter
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
        huggingface_available or
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
            else 'huggingface' if huggingface_available
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