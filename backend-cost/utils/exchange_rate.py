import os
import requests
import redis
from datetime import datetime, timedelta

redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

BOK_API_KEY = os.environ.get('BOK_API_KEY', '').strip()

def get_exchange_rate(date_str, _depth=0):
    """
    date_str: 'YYYY-MM-DD'
    returns: float (USD/KRW) or None if not available
    """
    # 무한 재귀 방지
    if _depth > 10:
        return None
    
    # Redis 캐시 확인
    cache_key = f'exchange_rate:{date_str}'
    cached = redis_client.get(cache_key)
    if cached:
        return float(cached)
    
    # 캐시가 없고 API 키가 설정되지 않으면 호출자의 기본 환율을 사용
    if not BOK_API_KEY:
        return None

    # 한국은행 API 호출
    date_fmt = date_str.replace('-', '')  # YYYYMMDD
    url = f'https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}/json/kr/1/1/731Y003/D/{date_fmt}/{date_fmt}/0000003'
    
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        
        if 'row' in data.get('StatisticSearch', {}):
            rate = float(data['StatisticSearch']['row'][0]['DATA_VALUE'])
            # 영구 캐시 (과거 환율은 변하지 않음)
            redis_client.setex(cache_key, 86400 * 365, str(rate))
            return rate
    except Exception:
        # 요청 URL에는 API 키가 포함되므로 예외 내용은 기록하지 않음
        print(f'Exchange rate API error for {date_str}')
    
    # 데이터 없음 (주말/공휴일/대체휴무) → 가장 가까운 영업일 환율 찾기
    from datetime import datetime, timedelta
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    
    # 전후 7일 범위에서 가장 가까운 영업일 찾기
    for offset in range(1, 8):
        # 이전 날짜 우선 (재무 관행)
        prev_date = (date_obj - timedelta(days=offset)).strftime('%Y-%m-%d')
        prev_rate = get_exchange_rate(prev_date, _depth + 1)
        if prev_rate:
            # 캐시에 저장 (공휴일도 직전 영업일 환율 사용)
            redis_client.setex(cache_key, 86400 * 365, str(prev_rate))
            return prev_rate
        
        # 다음 날짜 확인 (대체휴무 대응)
        next_date = (date_obj + timedelta(days=offset)).strftime('%Y-%m-%d')
        next_rate = get_exchange_rate(next_date, _depth + 1)
        if next_rate:
            redis_client.setex(cache_key, 86400 * 365, str(next_rate))
            return next_rate
    
    # 14일 범위에도 없으면 None
    return None

def get_monthly_avg_rate(year, month):
    """
    월 평균 환율 계산
    """
    from calendar import monthrange
    days = monthrange(year, month)[1]
    
    rates = []
    for day in range(1, days + 1):
        date_str = f'{year:04d}-{month:02d}-{day:02d}'
        rate = get_exchange_rate(date_str)
        if rate:  # None이 아닌 경우만
            rates.append(rate)
    
    return sum(rates) / len(rates) if rates else None
