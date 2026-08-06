import chess
import chess.engine
from chess.engine import INFO_ALL
import logging
import requests
import urllib.parse
from lib.engine_wrapper import MinimalEngine

logger = logging.getLogger(__name__)

class ExampleEngine(MinimalEngine):
    """An example engine that all homemade engines inherit."""

class MultiEngineRouter(MinimalEngine):
    def __init__(self, commands, options, stderr, draw_or_resign, game, debug=False, **kwargs):
        super().__init__(commands, options, stderr, draw_or_resign, game, debug, **kwargs)

        self.engine_stockfish = chess.engine.SimpleEngine.popen_uci(
            "/app/engines/drawfish", 
            debug=debug
        )
        self.engine_stockfish.configure({
            "Hash": 512,
            "Threads": 2
        })

        self.engine_fairy = chess.engine.SimpleEngine.popen_uci(
            "/app/engines/fairy-drawfish", 
            debug=debug
        )
        self.engine_fairy.configure({
            "Hash": 512,
            "Threads": 2
        })

    def check_online_syzygy_draw(self, board: chess.Board) -> str | None:
        """
        强制查询在线 Syzygy，寻找能达成和棋的最快走法。
        """
        # 1. 检查盘面棋子总数 (Lichess 最大支持 7 子)
        piece_count = chess.popcount(board.occupied)
        if piece_count > 7 or board.castling_rights:
            return None

        # 2. 检查变体支持
        variant = "standard" if board.uci_variant == "chess" else str(board.uci_variant)
        if variant not in ["standard", "atomic", "antichess"]:
            return None

        # 3. 请求 Lichess 在线 Syzygy API
        fen_quoted = urllib.parse.quote(board.fen())
        url = f"https://tablebase.lichess.ovh/{variant}?fen={fen_quoted}"

        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code != 200:
                return None
            data = resp.json()
        except Exception as e:
            logger.warning(f"查询在线 Syzygy 失败/超时: {e}")
            return None

        moves = data.get("moves", [])
        if not moves:
            return None

        # 4. 筛选出所有能够导致和棋（Draw）的走法
        draw_moves = []
        for m in moves:
            cat = m.get("category", "")
            is_instant_draw = m.get("stalemate") or m.get("insufficient_material")
            # draw, blessed-loss, cursed-win 都属于实际结果为和棋的情况
            if is_instant_draw or cat in ["draw", "blessed-loss", "cursed-win"]:
                draw_moves.append(m)

        if not draw_moves:
            return None

        # 5. 排序选出“最快和棋”的走法
        def draw_priority(m):
            if m.get("stalemate") or m.get("insufficient_material"):
                return (0, 0)
            dtm = m.get("dtm")
            if dtm is not None:
                return (1, abs(dtm))
            dtz = m.get("dtz")
            if dtz is not None:
                return (2, abs(dtz))
            return (3, 999)

        draw_moves.sort(key=draw_priority)
        best_draw_move = draw_moves[0]["uci"]
        logger.info(f"⚡ 在线 Syzygy 触发：成功找到最快和棋走法 [{best_draw_move}] (类别: {draw_moves[0].get('category')})")
        return best_draw_move

    def search(self, board: chess.Board, time_limit, ponder, draw_offered, root_moves):
        # 原生的 online_egtb 已被关闭，残局盘面会顺利传进这里
        
        # 1. 优先尝试寻找“最快和棋”走法
        fastest_draw_uci = self.check_online_syzygy_draw(board)
        if fastest_draw_uci:
            draw_move = chess.Move.from_uci(fastest_draw_uci)
            info = {
                "score": chess.engine.PovScore(chess.engine.Cp(0), board.turn),
                "string": "lichess-bot-source:Online Syzygy (Forced Fastest Draw)"
            }
            return chess.engine.PlayResult(draw_move, None, info=info)

        # 2. 正常走棋
        if board.uci_variant == "chess":
            target_engine = self.engine_stockfish
        else:
            target_engine = self.engine_fairy

        return target_engine.play(
            board,
            time_limit,
            info=INFO_ALL,
            ponder=ponder,
            draw_offered=draw_offered,
            root_moves=root_moves if isinstance(root_moves, list) else None
        )

    def notify(self, method_name: str, *args, **kwargs):
        if method_name == "quit":
            self.engine_stockfish.quit()
            self.engine_fairy.quit()