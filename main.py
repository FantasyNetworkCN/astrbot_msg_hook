import asyncio
import hmac
from aiohttp import web
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp

@register("msg_hook", "MinecraftNekoServer", "HTTP 消息转发插件", "1.1.3")
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
        value = self.config.get(key, default)
        if key == 'api_token':
            logger.info(f"读取配置 api_token: {'已设置' if value else '未设置'}")
        else:
            logger.info(f"读取配置 {key}: {value}")
        return value

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
            logger.info(f"收到 /send 请求，来源: {request.remote or '未知'}")
            # 验证 Token
            if not self.verify_token(request):
                logger.warning("/send 请求鉴权失败")
                return web.json_response({'success': False, 'error': '未授权访问'}, status=401)
            logger.info("/send 请求鉴权通过")

            # 检查是否启用转发
            if not self.get_config_value('enable_forward', True):
                logger.warning("/send 请求被拒绝：消息转发功能已禁用")
                return web.json_response({'success': False, 'error': '消息转发功能已禁用'}, status=403)

            data = await request.json()
            message = data.get('message', '')
            
            if not message:
                logger.warning("/send 请求被拒绝：消息内容为空")
                return web.json_response({'success': False, 'error': '消息内容不能为空'}, status=400)
            logger.info(f"/send 消息解析成功，长度: {len(str(message))}")

            target_groups = self.get_config_value('target_groups', [])
            target_sessions = self.get_config_value('target_sessions', [])
            logger.info(f"读取到的配置 target_groups: {target_groups}, 类型: {type(target_groups)}")
            logger.info(f"读取到的配置 target_sessions: {target_sessions}, 类型: {type(target_sessions)}")
            
            # 转换群号为整数
            target_groups = [int(g) for g in target_groups if g]
            logger.info(f"转换后的 target_groups: {target_groups}")
            
            if not target_groups and not target_sessions:
                logger.warning("/send 请求被拒绝：未配置任何目标群或会话")
                return web.json_response({'success': False, 'error': '未配置目标群号'}, status=400)

            # 添加前缀和后缀
            prefix = self.get_config_value('message_prefix', '')
            suffix = self.get_config_value('message_suffix', '')
            full_message = f"{prefix}{message}{suffix}"

            # 优先使用由 /开启消息 保存的 UMO，以确保消息发送到正确的平台和群聊。
            target_sessions = [str(session) for session in target_sessions if session]
            session_group_ids = set()
            for session in target_sessions:
                parts = session.rsplit(':', 2)
                if len(parts) == 3 and parts[1] == 'GroupMessage':
                    try:
                        session_group_ids.add(int(parts[2]))
                    except ValueError:
                        pass

            # 尚未保存 UMO 的旧配置继续使用原有发送方式。
            legacy_groups = [
                group_id for group_id in target_groups
                if group_id not in session_group_ids
            ]
            total_count = len(target_sessions) + len(legacy_groups)
            logger.info(
                f"准备发送消息：UMO 目标={target_sessions}，"
                f"兼容群号目标={legacy_groups}，总数={total_count}"
            )
            success_count = 0
            for session in target_sessions:
                try:
                    result = await self.send_to_session(session, full_message)
                    if result:
                        success_count += 1
                except Exception as e:
                    logger.exception(f"发送消息到会话 {session} 失败")

            for group_id in legacy_groups:
                try:
                    result = await self.send_to_group(group_id, full_message)
                    if result:
                        success_count += 1
                except Exception as e:
                    logger.exception(f"发送消息到群 {group_id} 失败")

            if success_count > 0:
                logger.info(f"消息已发送到 {success_count}/{total_count} 个目标")
                return web.json_response({
                    'success': True,
                    'message': f'消息已发送到 {success_count}/{total_count} 个目标'
                })
            else:
                logger.error("所有目标均发送失败")
                return web.json_response({'success': False, 'error': '所有群发送失败'}, status=500)

        except Exception as e:
            logger.exception("处理 /send 请求时发生未捕获异常")
            return web.json_response({'success': False, 'error': str(e)}, status=500)

    async def handle_health_check(self, request: web.Request):
        """健康检查接口"""
        return web.json_response({
            'status': 'ok',
            'target_groups': self.get_config_value('target_groups', []),
            'target_sessions': self.get_config_value('target_sessions', []),
            'server': {
                'host': self.get_config_value('server_host', '127.0.0.1'),
                'port': self.get_config_value('server_port', 8080)
            },
            'enable_forward': self.get_config_value('enable_forward', True)
        })

    async def send_to_group(self, group_id: int, message: str):
        """向旧版群号配置发送消息。"""
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
            logger.info(f"准备通过兼容群号方式发送：平台={platform_id}，会话={session_str}")
            message_chain = MessageChain(chain=[Comp.Plain(message)])
            result = await self.context.send_message(session_str, message_chain)
            logger.info(f"兼容群号发送调用完成：会话={session_str}，返回值={result!r}")
            return result is not False
        except Exception as e:
            logger.exception(f"兼容群号发送失败：群号={group_id}")
            return False

    async def send_to_session(self, session: str, message: str):
        """按 AstrBot 的统一消息来源（UMO）发送消息。"""
        try:
            logger.info(f"准备按 UMO 发送消息：会话={session}")
            message_chain = MessageChain(chain=[Comp.Plain(message)])
            result = await self.context.send_message(session, message_chain)
            logger.info(f"UMO 发送调用完成：会话={session}，返回值={result!r}")
            return result is not False
        except Exception as e:
            logger.exception(f"UMO 发送失败：会话={session}")
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

        target_sessions = self.get_config_value('target_sessions', [])
        current_session = event.unified_msg_origin
        group_already_enabled = group_id in normalized_groups
        session_already_enabled = not current_session or current_session in target_sessions
        if group_already_enabled and session_already_enabled:
            yield event.plain_result("当前群聊已启用消息转发。")
            return

        if not group_already_enabled:
            normalized_groups.append(group_id)
            self.config['target_groups'] = normalized_groups
        if not session_already_enabled:
            self.config['target_sessions'] = [*target_sessions, current_session]
        # 兼容未提供 save_config_async 的 AstrBot 版本，避免阻塞事件循环。
        await asyncio.to_thread(self.config.save_config)
        logger.info(f"已启用群 {group_id} 的消息转发")
        yield event.plain_result("已在当前群聊启用消息转发。")
