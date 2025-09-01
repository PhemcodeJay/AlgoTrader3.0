import os
import numpy as np
import pandas as pd
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, filename="app.log", filemode="a", format="%(asctime)s - %(levelname)s - %(message)s", encoding="utf-8")
logger = logging.getLogger(__name__)

load_dotenv()

from db import db

MODEL_PATH = os.getenv("ML_MODEL_PATH", "models/market_model.pkl")
ML_ENABLED = os.getenv("ML_ENABLED", "true").lower() == "true"

class MLFilter:
    def __init__(self):
        self.model = self._load_model() if ML_ENABLED else None
        self.db = db
        self._last_training_size = 0

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            logger.info("[ML] ✅ Loaded trained model.")
            return joblib.load(MODEL_PATH)
        else:
            logger.warning("[ML] ⚠️ No trained model found. Using fallback scoring.")
            return None

    def extract_features(self, signal: dict) -> np.ndarray:
        return np.array([
            signal.get("entry", 0),
            signal.get("tp", 0),
            signal.get("sl", 0),
            signal.get("trail", 0),
            signal.get("score", 0),
            signal.get("confidence", 0),
            1 if signal.get("side") == "LONG" else 0,
            1 if signal.get("trend") == "Up" else -1 if signal.get("trend") == "Down" else 0,
            1 if signal.get("regime") == "Breakout" else 0,
        ])

    def enhance_signal(self, signal: dict, trading_mode: str = "virtual") -> dict:
        if not ML_ENABLED:
            logger.info("[ML] ML disabled, using fallback scoring.")
            signal["score"] = signal.get("score", np.random.uniform(55, 70))
            signal["confidence"] = int(min(signal["score"] + np.random.uniform(5, 20), 100))
        elif self.model:
            features = self.extract_features(signal).reshape(1, -1)
            prob = self.model.predict_proba(features)[0][1]
            signal["score"] = round(prob * 100, 2)
            signal["confidence"] = int(min(signal["score"] + np.random.uniform(0, 10), 100))
        else:
            signal["score"] = signal.get("score", np.random.uniform(55, 70))
            signal["confidence"] = int(min(signal["score"] + np.random.uniform(5, 20), 100))

        try:
            entry_price = float(signal.get("entry", 0))
            leverage = int(signal.get("leverage", 20))
            capital = float(signal.get("capital", 100 if trading_mode == "virtual" else 0))

            if entry_price > 0 and leverage > 0:
                margin = capital / leverage
                signal["margin_usdt"] = round(margin, 2)
            else:
                signal["margin_usdt"] = 5.0
        except (ValueError, TypeError):
            signal["margin_usdt"] = 5.0

        return signal

    def load_data_from_db(self, limit=1000) -> list:
        combined = []
        trades = self.db.get_trades(limit=limit)
        for trade in trades:
            t = trade.to_dict()
            entry_price = t.get("entry_price") or 0
            exit_price = t.get("exit_price") or 0
            pnl = t.get("pnl")
            if entry_price and exit_price:
                direction = 1 if t.get("side") == "LONG" else -1
                profit = 1 if direction * (exit_price - entry_price) > 0 else 0
            else:
                profit = 1 if (pnl or 0) > 0 else 0

            combined.append({
                "entry": entry_price,
                "tp": t.get("take_profit") or 0,
                "sl": t.get("stop_loss") or 0,
                "trail": 0,
                "score": 60,
                "confidence": 60,
                "side": t.get("side") or "LONG",
                "trend": "Neutral",
                "regime": "Breakout",
                "profit": profit,
            })

        signals = self.db.get_signals(limit=limit)
        for signal in signals:
            s = signal.to_dict()
            indicators = s.get("indicators") or {}
            entry = s.get("entry") or indicators.get("entry") or 0
            tp = s.get("tp") or indicators.get("tp") or 0
            sl = s.get("sl") or indicators.get("sl") or 0

            combined.append({
                "entry": entry,
                "tp": tp,
                "sl": sl,
                "trail": indicators.get("trail") or 0,
                "score": s.get("score") or 60,
                "confidence": s.get("score") or 60,
                "side": s.get("side") or "LONG",
                "trend": indicators.get("trend") or "Neutral",
                "regime": indicators.get("regime") or "Breakout",
                "profit": 1 if (s.get("score") or 0) > 70 else 0,
            })

        logger.info(f"[ML] ✅ Loaded {len(combined)} total training records from DB.")
        return combined

    def train_from_db(self):
        if not ML_ENABLED:
            logger.info("[ML] ML disabled, skipping training.")
            return

        all_data = self.load_data_from_db()
        df = pd.DataFrame(all_data)

        if df.empty or len(df) < 30:
            logger.error(f"[ML] ❌ Not enough data to train. Found only {len(df)} rows.")
            return

        df["side_enc"] = df["side"].map({"LONG": 1, "SHORT": 0}).fillna(0)
        df["trend_enc"] = df["trend"].map({"Up": 1, "Down": -1, "Neutral": 0}).fillna(0)
        df["regime_enc"] = df["regime"].map({"Breakout": 1, "Mean": 0}).fillna(0)
        df = df.fillna(0)

        feature_columns = ["entry", "tp", "sl", "trail", "score", "confidence", "side_enc", "trend_enc", "regime_enc"]
        X = df[feature_columns]
        y = df["profit"]

        if len(y.unique()) < 2:
            logger.warning(f"[ML] ⚠️ Only one class found in target variable. Cannot train binary classifier.")
            return

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        model = XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42
        )

        try:
            model.fit(X_train, y_train)
            os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
            joblib.dump(model, MODEL_PATH)
            self.model = model

            acc = model.score(X_test, y_test)
            train_acc = model.score(X_train, y_train)

            self._last_training_size = len(df)

            logger.info(f"[ML] ✅ Model trained successfully!")
            logger.info(f"[ML] 📊 Training records: {len(df)}")
            logger.info(f"[ML] 🎯 Train accuracy: {train_acc:.2%}")
            logger.info(f"[ML] 🎯 Test accuracy: {acc:.2%}")
            logger.info(f"[ML] 💾 Model saved to: {MODEL_PATH}")
        except Exception as e:
            logger.error(f"[ML] ❌ Training failed: {e}")

    def update_model_with_new_data(self, min_new_records=10):
        if not ML_ENABLED:
            logger.info("[ML] ML disabled, skipping model update.")
            return False

        try:
            total_trades = self.db.get_trades_count()
            total_signals = self.db.get_signals_count()
            total_records = total_trades + total_signals
            new_records = total_records - self._last_training_size

            if new_records >= min_new_records:
                logger.info(f"[ML] 🔄 Found {new_records} new records. Retraining model...")
                self.train_from_db()
                return True
            else:
                logger.info(f"[ML] ℹ️ Only {new_records} new records. Minimum {min_new_records} required for retraining.")
                return False
        except Exception as e:
            logger.error(f"[ML] ❌ Failed to update model: {e}")
            return False

    def get_model_stats(self):
        stats = {
            "model_exists": self.model is not None,
            "model_path": MODEL_PATH,
            "model_file_exists": os.path.exists(MODEL_PATH),
            "ml_enabled": ML_ENABLED
        }
        try:
            data = self.load_data_from_db()
            df = pd.DataFrame(data)
            stats.update({
                "total_records": len(df),
                "profitable_records": int(sum(df["profit"])) if not df.empty else 0,
                "profit_rate": float(sum(df["profit"]) / len(df)) if not df.empty else 0,
                "trades_count": self.db.get_trades_count(),
                "signals_count": self.db.get_signals_count()
            })
        except Exception as e:
            stats["error"] = str(e)
        return stats

if __name__ == "__main__":
    ml = MLFilter()
    logger.info(f"[ML] 📊 Current model stats: {ml.get_model_stats()}")
    ml.train_from_db()