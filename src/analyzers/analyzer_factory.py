"""
分析器工厂
根据配置动态创建和管理不同类型的 AI 分析器
"""
import os
import sys
from typing import Dict, Any, Optional

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import ai_analysis_config
from src.analyzers.base_analyzer import BaseAnalyzer
from src.analyzers.local_analyzer import LocalAnalyzer
from src.utils.logger import LoggerMixin

class AnalyzerFactory(LoggerMixin):
    """分析器工厂类"""
    
    def __init__(self):
        super().__init__()
        self._analyzer_cache = {}
    
    def create_analyzer(self, analyzer_type: Optional[str] = None) -> BaseAnalyzer:
        """创建分析器实例"""
        if analyzer_type is None:
            analyzer_type = ai_analysis_config.analyzer_type
        
        # 检查缓存
        if analyzer_type in self._analyzer_cache:
            return self._analyzer_cache[analyzer_type]
        
        analyzer = None
        
        try:
            if analyzer_type.lower() == 'openai':
                analyzer = self._create_openai_analyzer()
            elif analyzer_type.lower() == 'azure':
                analyzer = self._create_azure_analyzer()
            elif analyzer_type.lower() == 'local':
                analyzer = self._create_local_analyzer()
            elif analyzer_type.lower() == 'notion':
                analyzer = self._create_notion_analyzer()
            else:
                self.logger.warning(f"未知的分析器类型: {analyzer_type}，使用本地分析器")
                analyzer = self._create_local_analyzer()
            
            # 缓存分析器实例
            self._analyzer_cache[analyzer_type] = analyzer
            self.logger.info(f"成功创建 {analyzer_type} 分析器")
            
        except Exception as e:
            self.logger.error(f"创建 {analyzer_type} 分析器失败: {e}")
            self.logger.info("回退到本地分析器")
            analyzer = self._create_local_analyzer()
            self._analyzer_cache[analyzer_type] = analyzer
        
        return analyzer
    
    def _create_openai_analyzer(self) -> BaseAnalyzer:
        """创建 OpenAI 分析器"""
        try:
            from src.analyzers.openai_analyzer import OpenAIAnalyzer
            return OpenAIAnalyzer()
        except ImportError as e:
            raise ImportError(f"OpenAI 分析器依赖缺失: {e}")
    
    def _create_azure_analyzer(self) -> BaseAnalyzer:
        """创建 Azure 分析器"""
        try:
            from src.analyzers.azure_analyzer import AzureAnalyzer
            return AzureAnalyzer()
        except ImportError as e:
            raise ImportError(f"Azure 分析器依赖缺失: {e}")
    
    def _create_local_analyzer(self) -> BaseAnalyzer:
        """创建本地分析器"""
        return LocalAnalyzer()
    
    def _create_notion_analyzer(self) -> BaseAnalyzer:
        """创建 Notion AI 分析器"""
        try:
            from src.analyzers.notion_analyzer import NotionAnalyzer
            return NotionAnalyzer()
        except ImportError as e:
            raise ImportError(f"Notion 分析器依赖缺失: {e}")
    
    def get_available_analyzers(self) -> Dict[str, Dict[str, Any]]:
        """获取可用的分析器列表"""
        analyzers = {}
        
        # 本地分析器（总是可用）
        analyzers['local'] = {
            'name': '本地分析器',
            'description': '基于规则的快速分析，无需外部 API',
            'available': True,
            'dependencies': []
        }
        
        # OpenAI 分析器
        try:
            import openai
            from config.settings import openai_config
            analyzers['openai'] = {
                'name': 'OpenAI 分析器',
                'description': '使用 OpenAI GPT 模型进行高质量分析',
                'available': bool(openai_config.api_key),
                'dependencies': ['openai'],
                'base_url': openai_config.base_url,
                'model': openai_config.model
            }
        except ImportError:
            analyzers['openai'] = {
                'name': 'OpenAI 分析器',
                'description': '使用 OpenAI GPT 模型进行高质量分析',
                'available': False,
                'dependencies': ['openai'],
                'error': '缺少 openai 库'
            }
        
        # Azure 分析器
        try:
            from config.settings import azure_config
            analyzers['azure'] = {
                'name': 'Azure Text Analytics',
                'description': '微软 Azure 认知服务文本分析',
                'available': bool(azure_config.api_key and azure_config.endpoint),
                'dependencies': ['azure-ai-textanalytics'],
                'endpoint': azure_config.endpoint
            }
        except ImportError:
            analyzers['azure'] = {
                'name': 'Azure Text Analytics',
                'description': '微软 Azure 认知服务文本分析',
                'available': False,
                'dependencies': ['azure-ai-textanalytics'],
                'error': '缺少 Azure 库'
            }
        
        # Notion AI 分析器
        analyzers['notion'] = {
            'name': 'Notion AI 分析器',
            'description': '使用 Notion 内置 AI 功能进行分析',
            'available': False,  # 暂未实现
            'dependencies': ['notion-client'],
            'note': '计划中的功能'
        }
        
        return analyzers
    
    def health_check_all(self) -> Dict[str, Dict[str, Any]]:
        """检查所有分析器的健康状态"""
        results = {}
        available_analyzers = self.get_available_analyzers()
        
        for analyzer_type, info in available_analyzers.items():
            if info['available']:
                try:
                    analyzer = self.create_analyzer(analyzer_type)
                    results[analyzer_type] = analyzer.health_check()
                except Exception as e:
                    results[analyzer_type] = {
                        'status': 'unhealthy',
                        'analyzer': analyzer_type,
                        'error': str(e)
                    }
            else:
                results[analyzer_type] = {
                    'status': 'unavailable',
                    'analyzer': analyzer_type,
                    'reason': info.get('error', '配置不完整')
                }
        
        return results
    
    def clear_cache(self):
        """清空分析器缓存"""
        self._analyzer_cache.clear()
        self.logger.info("分析器缓存已清空")

# 全局工厂实例
analyzer_factory = AnalyzerFactory() 