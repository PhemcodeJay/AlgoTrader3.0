import streamlit as st
import logging
import pandas as pd
from datetime import datetime
from ml import MLFilter

logger = logging.getLogger(__name__)

def show_ml(db, engine, client, trading_mode: str):
    """Display the Machine Learning page for model management and statistics"""
    try:
        st.title("🧠 Machine Learning")
        st.markdown("---")

        # Initialize MLFilter
        ml_filter = MLFilter()

        # Model Status
        st.subheader("Model Status")
        model_stats = ml_filter.get_model_stats()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Model Loaded", "✅ Yes" if model_stats.get("model_exists") else "❌ No")
        with col2:
            st.metric("Total Records", model_stats.get("total_records", 0))
        with col3:
            st.metric("Profit Rate", f"{model_stats.get('profit_rate', 0):.2%}")

        st.caption(f"Model Path: {model_stats.get('model_path', 'N/A')}")
        st.caption(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        st.markdown("---")

        # Training Controls
        st.subheader("Model Training")
        if st.button("🔄 Retrain Model", key="retrain_model"):
            with st.spinner("Training model..."):
                ml_filter.train_from_db()
                st.success("✅ Model retraining completed!")
                st.rerun()

        # Auto-update settings
        min_records = st.number_input(
            "Minimum new records for auto-update",
            min_value=1,
            max_value=100,
            value=10,
            step=1,
            key="min_records"
        )
        if st.button("Check for New Data", key="check_new_data"):
            with st.spinner("Checking for new data..."):
                updated = ml_filter.update_model_with_new_data(min_records)
                if updated:
                    st.success("✅ Model updated with new data!")
                    st.rerun()
                else:
                    st.info(f"ℹ️ Not enough new data ({min_records} required)")

        st.markdown("---")

        # Model Performance
        st.subheader("Model Performance")
        try:
            data = ml_filter.load_data_from_db()
            if data:
                df = pd.DataFrame(data)
                st.write("Recent Training Data Preview")
                st.dataframe(
                    df[["entry", "tp", "sl", "side", "score", "confidence", "profit"]].tail(10),
                    use_container_width=True
                )

                # Performance Metrics
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Total Trades", model_stats.get("trades_count", 0))
                with col2:
                    st.metric("Total Signals", model_stats.get("signals_count", 0))

                # Profit Distribution
                if not df.empty:
                    st.write("Profit Distribution")
                    profit_counts = df["profit"].value_counts()
                    st.bar_chart(profit_counts)
            else:
                st.info("ℹ️ No training data available")
        except Exception as e:
            logger.error(f"Error displaying model performance: {e}")
            st.error(f"🚨 Error displaying model performance: {str(e)}")

    except Exception as e:
        logger.error(f"Error in ML page: {e}")
        st.error(f"🚨 Error loading ML page: {str(e)}")

if __name__ == "__main__":
    show_ml(db=None, engine=None, client=None, trading_mode="virtual")