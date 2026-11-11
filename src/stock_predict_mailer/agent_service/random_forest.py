"""Export the delivered monthly classifier through the v1 prediction contract."""
from __future__ import annotations

import hashlib
import json
import pickle
import warnings
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import ServiceError, decode, keys, number, prediction, string, utcnow

MODEL_PATH = Path('src/数据面/随机森林_数据面模型.pkl')
MODEL_DIGEST = '03c9b627004c39b9a60f292770417aaf561bc34fb2d41f829be5baf07f850dda'
SKLEARN_VERSION = '1.9.1'
FEATURES = ('PB分位', '收益率', '均线偏移', '动量_20日', '量价相关_10日', '波动率_60日', '价格位置_20日', 'roe_delta_r', 'eps_yoy_r')


def predict_file(feature_path, model_path=MODEL_PATH):
    with Path(feature_path).open('rb') as stream:
        raw = decode(stream.read(1024 * 1024 + 1))
    keys(raw, ('subject', 'as_of', 'synthetic', 'features'))
    subject = string(raw['subject'])
    try:
        as_of = date.fromisoformat(raw['as_of'])
    except (TypeError, ValueError):
        raise ServiceError('INVALID_INPUT', 'as_of 须为 YYYY-MM-DD') from None
    now = utcnow()
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    if type(raw['synthetic']) is not bool or as_of > today:
        raise ServiceError('INVALID_INPUT', 'synthetic 须为布尔值，特征日期不能晚于今天')
    next_year, next_month = as_of.year + (as_of.month == 12), as_of.month % 12 + 1
    horizon_days = monthrange(next_year, next_month)[1]
    target_end = date(next_year, next_month, horizon_days)
    if target_end < today and not raw['synthetic']:
        raise ServiceError('INVALID_INPUT', '实盘预测的目标月已结束，请提供新的月频特征')
    keys(raw['features'], FEATURES)
    values = [number(raw['features'][name]) for name in FEATURES]

    with Path(model_path).open('rb') as stream:
        artifact = stream.read(1024 * 1024 + 1)
    if hashlib.sha256(artifact).hexdigest() != MODEL_DIGEST:
        raise ServiceError('CONFIG_ERROR', '模型文件与已接入的训练交付版本不一致')
    try:
        import sklearn
    except ModuleNotFoundError:
        raise ServiceError('CONFIG_ERROR', '随机森林推理需要安装 research 可选依赖') from None
    if sklearn.__version__ != SKLEARN_VERSION:
        raise ServiceError('CONFIG_ERROR', f'该模型需要 scikit-learn {SKLEARN_VERSION}')
    bundle = pickle.loads(artifact)  # Accept only the exact Git-delivered artifact verified above.
    model = bundle['model']
    if tuple(bundle['FEATS']) != FEATURES or tuple(model.feature_names_in_) != FEATURES or list(model.classes_) != [0, 1]:
        raise ServiceError('CONFIG_ERROR', '模型的特征顺序或分类标签与训练契约不一致')
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='X does not have valid feature names', category=UserWarning)
        score = float(model.predict_proba([values])[0][1])
    identity = hashlib.sha256(json.dumps(raw, sort_keys=True, allow_nan=False).encode()).hexdigest()[:20]
    return prediction({
        'schema_version': '1', 'prediction_id': f'rf-{MODEL_DIGEST[:12]}-{identity}', 'subject': subject,
        'generated_at': now.isoformat(), 'valid_until': (now + timedelta(days=1)).isoformat(),
        'horizon': {'value': horizon_days, 'unit': 'calendar_days'},
        'value': score, 'value_unit': '下月收益截面排名前30%的模型概率', 'confidence': None,
        'model_version': f'rf-monthly-{MODEL_DIGEST[:12]}', 'synthetic': raw['synthetic'],
        'metrics': {'feature_date_yyyymmdd': int(as_of.strftime('%Y%m%d')), 'target_month_yyyymm': next_year * 100 + next_month,
                    'validation_auc': float(bundle['验证_AUC_测试'])},
    }, now=now)
