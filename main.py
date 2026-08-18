import asyncio
import hmac
from aiohttp import web
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp

@register("msg_hook", "MinecraftNekoServer", "HTTP 消息转发插件", "1.1.1")
class MsgHookPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.app = None
        self.runner = None
        self.site = None

    async def initialize(self):
        """初始化插件，启动 HTTP 服务器"""
        await self.start_http_server()

    def get_config_value(self, key, default=None):
        """获取配置值"""
        logger.info(f"请求的键: {key}, 值: {self.config.get(key, default)}")
        return self.config.get(key, default)

    async def start_http_server(self):
        """启动 HTTP 服务器"""
        self.app = web.Application()
        self.app.router.add_post('/send', self.handle_send_request)
        self.app.router.add_get('/health', self.handle_health_check)

        host = self.get_config_value('server_host', '127.0.0.1')
        port = self.get_config_value('server_port', 8080)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()

        target_groups = self.get_config_value('target_groups', [])
        logger.info(f"HTTP 服务器已启动，监听 {host}:{port}")
        logger.info(f"目标群号: {target_groups}")
        logger.info(f"消息转发: {'启用' if self.get_config_value('enable_forward', True) else '禁用'}")

    def verify_token(self, request: web.Request) -> bool:
        """验证 API Token，兼容 ``Bearer <token>`` 和直接传入 token。"""
        token = self.get_config_value('api_token', '')
        if not token:
            return True

        auth_header = request.headers.get('Authorization', '')
        supplied_token = auth_header[7:] if auth_header.startswith('Bearer ') else auth_header
        return hmac.compare_digest(supplied_token, str(token))

    async def handle_send_request(self, request: web.Request):
        """处理发送消息的 HTTP 请求"""
        try:
            # 验证 Token
            if not self.verify_token(request):
                return web.json_response({'success': False, 'error': '未授权访问'}, status=401)

            # 检查是否启用转发
            if not self.get_config_value('enable_forward', True):
                return web.json_response({'success': False, 'error': '消息转发功能已禁用'}, status=403)

            data = await request.json()
            message = data.get('message', '')
            
            if not message:
                return web.json_response({'success': False, 'error': '消息内容不能为空'}, status=400)

            target_groups = self.get_config_value('target_groups', [])
            logger.info(f"读取到的配置 target_groups: {target_groups}, 类型: {type(target_groups)}")
            
            # 转换群号为整数
            target_groups = [int(g) for g in target_groups if g]
            logger.info(f"转换后的 target_groups: {target_groups}")
            
            if not target_groups:
                return web.json_response({'success': False, 'error': '未配置目标群号'}, status=400)

            # 添加前缀和后缀
            prefix = self.get_config_value('message_prefix', '')
            suffix = self.get_config_value('message_suffix', '')
            full_message = f"{prefix}{message}{suffix}"

            # 转发消息到所有目标群
            success_count = 0
            for group_id in target_groups:
                try:
                    result = await self.send_to_group(group_id, full_message)
                    if result:
                        success_count += 1
                except Exception as e:
                    logger.error(f"发送消息到群 {group_id} 失败: {e}")

            if success_count > 0:
                logger.info(f"消息已发送到 {success_count}/{len(target_groups)} 个群")
                return web.json_response({
                    'success': True,
                    'message': f'消息已发送到 {success_count}/{len(target_groups)} 个群'
                })
            else:
                return web.json_response({'success': False, 'error': '所有群发送失败'}, status=500)

        except Exception as e:
            logger.error(f"处理请求时发生错误: {e}")
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_health_check(self, request: web.Request):
        """健康检查接口"""
        return web.json_response({
            'status': 'ok',
            'target_groups': self.get_config_value('target_groups', []),
            'server': {
                'host': self.get_config_value('server_host', '127.0.0.1'),
                'port': self.get_config_value('server_port', 8080)
            },
            'enable_forward': self.get_config_value('enable_forward', True)
        })

    async def send_to_group(self, group_id: int, message: str):
        """发送消息到指定群"""
        try:
            # 获取平台适配器实例，使用第一个可用的平台
            platforms = self.context.platform_manager.platform_insts
            if not platforms:
                logger.error("没有可用的消息平台")
                return False
            
            platform = platforms[0]
            platform_id = platform.meta().id
            
            # 构造 session 字符串: platform_id:GroupMessage:group_id
            session_str = f"{platform_id}:GroupMessage:{group_id}"
            
            message_chain = MessageChain(chain=[Comp.Plain(message)])
            result = await self.context.send_message(session_str, message_chain)
            return True
        except Exception as e:
            logger.error(f"发送群消息失败: {e}")
            return False

    async def terminate(self):
        """插件销毁方法，关闭 HTTP 服务器"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("HTTP 服务器已停止")

    @filter.command("msg_status")
    async def status(self, event: AstrMessageEvent):
        """查看插件状态"""
        host = self.get_config_value('server_host', '127.0.0.1')
        port = self.get_config_value('server_port', 8080)
        target_groups = self.get_config_value('target_groups', [])
        enable_forward = self.get_config_value('enable_forward', True)
        has_token = bool(self.get_config_value('api_token', ''))
        
        status_text = (
            f"【消息转发插件状态】\n"
            f"服务器: {host}:{port}\n"
            f"目标群号: {', '.join(map(str, target_groups)) if target_groups else '未配置'}\n"
            f"群数量: {len(target_groups)}\n"
            f"转发状态: {'启用' if enable_forward else '禁用'}\n"
            f"Token 验证: {'启用' if has_token else '禁用'}"
        )
        yield event.plain_result(status_text)

    @filter.command("开启消息")
    async def enable_current_group(self, event: AstrMessageEvent):
        """将当前群聊添加到消息转发目标列表。"""
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令仅可在群聊中使用。")
            return

        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            logger.warning(f"无法识别当前群号: {group_id}")
            yield event.plain_result("无法识别当前群号，开启失败。")
            return

        target_groups = self.get_config_value('target_groups', [])
        # 兼容旧配置中可能存在的字符串群号。
        normalized_groups = []
        for target_group in target_groups:
            try:
                normalized_groups.append(int(target_group))
            except (TypeError, ValueError):
                logger.warning(f"忽略无效的目标群号配置: {target_group}")

        if group_id in normalized_groups:
            yield event.plain_result("当前群聊已启用消息转发。")
            return

        normalized_groups.append(group_id)
        self.config['target_groups'] = normalized_groups
        # 兼容未提供 save_config_async 的 AstrBot 版本，避免阻塞事件循环。
        await asyncio.to_thread(self.config.save_config)
        logger.info(f"已启用群 {group_id} 的消息转发")
        yield event.plain_result("已在当前群聊启用消息转发。")
