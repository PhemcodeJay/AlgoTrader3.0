import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AutomatedTrader:
    """Automated trading system"""
    
    def __init__(self, engine):
        self.is_running = False
        self.thread = None
        self.start_time = None
        self.engine = engine
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        
    def start(self) -> bool:
        """Start the automated trading system"""
        if self.is_running:
            logger.warning("Automation is already running")
            return False
            
        try:
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            self.thread = threading.Thread(target=self._trading_loop, daemon=True)
            self.thread.start()
            logger.info("Automated trading system started")
            return True
        except Exception as e:
            logger.error(f"Failed to start automation: {e}")
            self.is_running = False
            return False
    
    def stop(self):
        """Stop the automated trading system"""
        if not self.is_running:
            logger.warning("Automation is not running")
            return
            
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("Automated trading system stopped")
    
    def _trading_loop(self):
        """Main trading loop"""
        logger.info("Trading loop started")
        
        while self.is_running:
            try:
                # Generate signals
                signals = self.engine.run_once()
                self.stats["signals_generated"] += len(signals)
                
                # Execute top signals
                for signal in signals:
                    trade = self.engine.execute_signal(signal)
                    if trade:
                        self.stats["trades_executed"] += 1
                
                # Update success rate
                trade_stats = self.engine.get_trade_statistics()
                self.stats["success_rate"] = trade_stats.get("win_rate", 0.0)
                
                self._update_uptime()
                time.sleep(60)  # Run every minute
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                time.sleep(30)  # Wait before retrying
    
    def _update_uptime(self):
        """Update uptime"""
        if self.start_time:
            uptime = datetime.now(timezone.utc) - self.start_time
            hours, remainder = divmod(uptime.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.stats["uptime"] = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
    
    def get_status(self) -> Dict:
        """Get current automation status"""
        return {
            "is_running": self.is_running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "stats": self.stats.copy()
        }
    
    def reset_stats(self):
        """Reset trading statistics"""
        self.stats = {
            "signals_generated": 0,
            "trades_executed": 0,
            "success_rate": 0.0,
            "uptime": "0:00:00"
        }
        logger.info("Statistics reset")

# Global instance (instantiate with engine in app.py)