"""
Hybrid Engine v1
محرك هجين صغير لكن صارم: يحدد نوع السوق/الاستراتيجية، يمنع الإشارات الضعيفة،
ويمنح نقاطاً إضافية فقط للإعدادات عالية الجودة.

الهدف: ليس فتح صفقات أكثر، بل فتح صفقات أوضح وأفضل R:R.
"""
import logging
import config as cfg

logger = logging.getLogger("hybrid_engine")


def _f(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _regime_name(signal):
    regime = (signal.get('market_regime') or {}).get('regime') or signal.get('regime') or 'UNKNOWN'
    return str(regime).upper()


def _direction(signal):
    return str(signal.get('direction', '')).upper()


def evaluate_signal(signal, analysis, score_details):
    """
    يرجع: (allow, adjusted_score, strategy, info)
    - allow: هل نسمح باستدعاء الـ AI والدخول المحتمل؟
    - adjusted_score: النقاط بعد مكافآت/عقوبات الهجين
    - strategy: TREND_SCALP / BREAKOUT / RANGE_REVERT / NO_SETUP
    - info: يُضاف داخل score_details للتتبع
    """
    total_score = _f((score_details or {}).get('total'), 0.0)
    info = {
        'hybrid_points': 0,
        'hybrid_strategy': 'OFF',
        'hybrid_reasons': [],
    }

    if not getattr(cfg, 'USE_HYBRID_ENGINE', True):
        return True, total_score, 'HYBRID_OFF', info

    direction = _direction(signal)
    regime = _regime_name(signal)

    alignment = _f(signal.get('timeframe_alignment', analysis.get('timeframe_alignment', 0)))

    # استخراج الحقول من بنية التحليل الفعلية وليس من مفاتيح غير موجودة
    volume_info = analysis.get('volume_analysis') or {}
    volume = _f(signal.get('volume_ratio') or volume_info.get('volume_5m_ratio') or volume_info.get('volume_ratio') or 0)

    technical = analysis.get('technical_indicators') or {}
    rsi = _f(signal.get('rsi') or technical.get('rsi', 50), 50)

    pa_info = analysis.get('price_action') or {}
    body = abs(_f(signal.get('body_percent') or pa_info.get('body_ratio') or pa_info.get('body_percent') or 0))

    mom_info = analysis.get('momentum') or {}
    momentum_strength = _f(mom_info.get('strength', 0))
    momentum_dir = str(mom_info.get('direction', '')).strip()

    confidence = _f(signal.get('confidence', 0))

    orderbook = _f((score_details or {}).get('order_book_points', 0))
    funding_oi = _f((score_details or {}).get('funding_oi_points', 5), 5)
    pa_points = _f((score_details or {}).get('price_action_points', 0))
    momentum_points = _f((score_details or {}).get('momentum_points', 0))

    reasons = []
    score = total_score
    allow = True

    # 🧠 ذاكرة الرموز: لا تكرر العملات التي ثبتت خسارتها مؤخراً
    try:
        import trade_memory
        symbol_mem = trade_memory.get_symbol_score(symbol) or {}
        info['symbol_memory'] = symbol_mem
        if not symbol_mem.get('should_trade', True):
            allow = False
            reasons.append(f'الرمز ضعيف حديثاً: score={symbol_mem.get("score", 0):.0f}')
        elif _f(symbol_mem.get('score', 100), 100) < 50:
            score -= 10
            reasons.append('عقوبة رمز ضعيف')
    except Exception:
        pass

    # فلتر صلابة أساسي
    if volume < 0.65 and not (alignment >= 9 and body >= 0.70 and orderbook >= 5):
        allow = False
        reasons.append(f'حجم ضعيف جداً {volume:.2f}x')
    if alignment <= 3.5 and regime not in ('RANGE', 'NEUTRAL'):
        allow = False
        reasons.append(f'ترابط ضعيف {alignment:.1f} في سوق غير رينج')
    if confidence < _f(getattr(cfg, 'MIN_CONFIDENCE_AUTO', 60), 60):
        allow = False
        reasons.append(f'ثقة AI منخفضة {confidence:.0f}%')

    # منع الدخول العكسي للترند القوي
    if regime in ('STRONG_UP', 'UP', 'BULLISH') and direction == 'SELL':
        allow = False
        reasons.append('بيع عكس ترند صاعد قوي')
    if regime in ('STRONG_DOWN', 'DOWN', 'BEARISH') and direction == 'BUY':
        allow = False
        reasons.append('شراء عكس ترند هابط قوي')

    # تحديد الاستراتيجية
    strategy = 'NO_SETUP'
    aligned_momentum = (
        (direction == 'BUY' and momentum_dir == 'صاعد') or
        (direction == 'SELL' and momentum_dir == 'هابط')
    )

    if alignment >= 8 and volume >= 1.5 and body >= 0.60 and aligned_momentum and orderbook >= 3:
        strategy = 'BREAKOUT'
        score += 12
        reasons.append('اختراق قوي بحجم وترابط')
    elif alignment >= 8 and volume >= 0.9 and body >= 0.30 and aligned_momentum and orderbook >= 2:
        strategy = 'TREND_SCALP'
        score += 8
        reasons.append('ترند سليم قابل للخطف السريع')
    elif alignment <= 6 and ((direction == 'BUY' and rsi <= 35) or (direction == 'SELL' and rsi >= 65)):
        strategy = 'RANGE_REVERT'
        score += 5
        reasons.append('ارتداد رينج فقط')
    else:
        score -= 10
        reasons.append('لا توجد استراتيجية واضحة')

    # عقوبات جودة — متوازنة وليست مشللة
    if volume < 1.0:
        score -= 3
        reasons.append('حجم أقل من المتوسط')
    if volume < 0.8:
        score -= 3
        reasons.append('حجم منخفض جداً')
    if alignment < 6:
        score -= 4
        reasons.append('ترابط ضعيف')
    if orderbook <= 2:
        score -= 3
        reasons.append('دفتر أوامر ضعيف')
    if funding_oi <= 4:
        score -= 2
        reasons.append('Funding/OI غير مؤيد')
    if pa_points <= 3:
        score -= 3
        reasons.append('PA ضعيف')
    if momentum_points <= 3:
        score -= 2
        reasons.append('Momentum غير حاسم')
    # 🏛️ سياق السوق: اتجاه فريم أعلى + بنية السعر + منع الترابط
    try:
        import market_structure
        context = market_structure.get_market_context(symbol, direction)
        htf_bias = (context.get('htf') or {}).get('bias', 'UNKNOWN')
        struct = context.get('structure') or {}
        corr = context.get('correlation') or {}
        info['htf_bias'] = htf_bias
        info['market_structure'] = struct
        info['correlation'] = corr

        desired_htf = 'BULLISH' if direction == 'BUY' else 'BEARISH'
        opposite_htf = 'BEARISH' if direction == 'BUY' else 'BULLISH'
        if htf_bias == desired_htf:
            score += 3
            reasons.append('HTF مع الاتجاه')
        elif htf_bias == opposite_htf:
            score -= 6
            reasons.append('HTF عكس الاتجاه')

        setup = struct.get('setup', 'NONE')
        if setup in ('BREAKOUT', 'PULLBACK'):
            score += 5
            reasons.append(f'بنية سعر واضحة: {setup}')
            if strategy == 'NO_SETUP':
                strategy = 'TREND_SCALP'
        elif setup == 'RANGE_REVERSAL':
            score += 2
            reasons.append('ارتداد رينج من البنية')
        elif setup == 'NONE':
            score -= 4
            reasons.append('لا توجد بنية سعر واضحة')

        # RSI المتطرف ليس عدواً بحد ذاته داخل ترند واضح
        if direction == 'BUY' and rsi >= 70 and not (htf_bias == 'BULLISH' or setup == 'BREAKOUT'):
            score -= 3
            reasons.append('RSI مرتفع بدون ترند داعم')
        if direction == 'SELL' and rsi <= 30 and not (htf_bias == 'BEARISH' or setup == 'BREAKOUT'):
            score -= 3
            reasons.append('RSI منخفض بدون ترند داعم')

        if corr.get('conflict'):
            allow = False
            reasons.append(corr.get('reason', 'تعارض ارتباط'))
    except Exception as e:
        logger.debug(f"market_structure skipped: {e}")

    score = max(0, min(100, score))
    info['hybrid_points'] = round(score - total_score, 2)
    info['hybrid_strategy'] = strategy
    info['hybrid_reasons'] = reasons

    min_required = _f(getattr(cfg, 'MIN_SCORE_REQUIRED', 55), 55)
    opp_min = _f(getattr(cfg, 'OPPORTUNITY_MIN_SCORE', 70), 70)
    opportunity_candidate = (
        score >= opp_min and score < min_required and
        strategy in ('TREND_SCALP', 'BREAKOUT') and
        volume >= 1.0 and alignment >= 8 and body >= 0.35 and orderbook >= 3
    )
    if opportunity_candidate:
        info['opportunity_candidate'] = True
        reasons.append('فرصة محتملة بانتظار AI')
    elif score < min_required:
        allow = False
        reasons.append(f'النقاط النهائية {score:.0f} < {min_required:.0f}')

    return allow, score, strategy, info
