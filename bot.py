import os
from openai import OpenAI
from dotenv import load_dotenv

class Bot:
    def __init__(self, env_path=None):
        if env_path is None:
            # 显式指定.env文件路径（确保和bot.py同目录）
            # __file__ 代表当前脚本的路径，dirname取目录名
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
        
        load_dotenv(dotenv_path=env_path)  # 加载指定路径的.env文件
        
        # 读取环境变量
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL")
        self.model = os.getenv("OPENAI_MODEL")
        
        if not self.api_key:
            raise ValueError("DASHSCOPE_API_KEY 环境变量未加载成功，请检查.env文件")
        if not self.model:
            raise ValueError("OPENAI_MODEL 环境变量未设置")
            
        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def chat(self, prompt: str = None, messages: list = None, **kwargs) -> str:
        """发送单轮对话请求"""
        try:
            if messages is None:
                messages = [{"role": "user", "content": prompt}]
            
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs
            )
            return completion.choices[0].message.content
        except Exception as e:
            print(f"调用 API 出现错误：{e}")
            raise e

    def chat_stream(self, prompt: str = None, messages: list = None, **kwargs):
        """发送单轮对话请求（流式）"""
        try:
            if messages is None:
                messages = [{"role": "user", "content": prompt}]
            
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                **kwargs
            )
            
            for chunk in completion:
                if len(chunk.choices) > 0:
                    delta_content = chunk.choices[0].delta.content or ""
                    if delta_content:
                        yield delta_content
                # we can also handle chunk.usage if needed, but for now we just yield content
        except Exception as e:
            print(f"调用 API 出现错误：{e}")
            raise e

if __name__ == "__main__":
    try:
        # 初始化 Bot
        bot = Bot()
        
        print(f"api_key: {'已加载（隐藏）' if bot.api_key else 'None'}")
        print(f"base_url: {bot.base_url}")
        print(f"model: {bot.model}")
        
        # 测试调用（可选，验证是否能正常连接）
        print("正在发送请求...")
        response = bot.chat("你好")
        print("API调用成功！回复：", response)
        
    except ValueError as e:
        print(f"配置错误：{e}")
    except Exception as e:
        print(f"错误信息：{e}")