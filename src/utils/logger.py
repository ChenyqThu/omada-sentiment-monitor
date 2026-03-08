"""
日志系统模块
提供统一的日志配置和管理
"""
import logging
import logging.handlers
import os
import sys
from typing import Optional
from datetime import datetime

from config.settings import system_config

class CustomFormatter(logging.Formatter):
    """自定义日志格式器，支持彩色输出"""
    
    # 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色  
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[35m', # 紫色
    }
    RESET = '\033[0m'
    
    def format(self, record):
        # 添加颜色（仅在终端输出时）
        if hasattr(sys.stderr, 'isatty') and sys.stderr.isatty():
            color = self.COLORS.get(record.levelname, '')
            reset = self.RESET
        else:
            color = reset = ''
            
        # 自定义格式
        log_format = f"{color}%(asctime)s [%(levelname)s] %(name)s: %(message)s{reset}"
        formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)

def setup_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """
    设置日志器
    
    Args:
        name: 日志器名称
        log_file: 日志文件路径（可选）
    
    Returns:
        配置好的日志器
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 设置日志级别
    log_level = getattr(logging, system_config.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(CustomFormatter())
    logger.addHandler(console_handler)
    
    # 文件处理器
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 使用轮转文件处理器
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        
        # 文件日志格式（不含颜色）
        file_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger

def get_logger(name: str, log_file: Optional[str] = None) -> logging.Logger:
    """
    获取日志器的便捷方法
    
    Args:
        name: 日志器名称
        log_file: 日志文件路径（可选）
    
    Returns:
        日志器实例
    """
    return setup_logger(name, log_file)

class LoggerMixin:
    """日志混入类，为其他类提供日志功能"""
    
    @property
    def logger(self) -> logging.Logger:
        """获取日志器"""
        if not hasattr(self, '_logger'):
            class_name = self.__class__.__name__
            log_file = f"logs/{class_name.lower()}.log"
            self._logger = get_logger(class_name, log_file)
        return self._logger
    
    def log_method_call(self, method_name: str, **kwargs):
        """记录方法调用日志"""
        if kwargs:
            params = ', '.join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.debug(f"调用方法 {method_name}({params})")
        else:
            self.logger.debug(f"调用方法 {method_name}()")
    
    def log_execution_time(self, method_name: str, start_time: datetime, end_time: datetime):
        """记录方法执行时间"""
        duration = (end_time - start_time).total_seconds()
        self.logger.info(f"{method_name} 执行完成，耗时: {duration:.2f}秒")

 