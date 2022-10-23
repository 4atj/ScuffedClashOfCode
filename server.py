from __future__ import annotations

import math
import json
import asyncio
from time import time
from enum import IntEnum
from random import choice
from typing import Any, Final, ClassVar, Optional

from sanic import Sanic
from sanic.application.constants import ServerStage
from sanic.server.websockets.impl import WebsocketImplProtocol
from websockets.exceptions import ConnectionClosed, ConnectionClosedError
from sanic.request import Request

from pistonapi import PistonAPI, PistonError
from typing import Final


piston: Final = PistonAPI()
app: Final = Sanic("GAME", log_config={"version": 1})

app.config.WEBSOCKET_PING_INTERVAL = None  # type: ignore
app.config.WEBSOCKET_PING_TIMEOUT = None  # type: ignore

@app.websocket("/", name='ws')
async def ws_handler(request: Request, ws: WebsocketImplProtocol):
    player = Player(ws)
    await player.ws_handler()

class SubmissionState(IntEnum):
    in_progess = 0
    pending = 1
    finished = 2

class MessageRecvID(IntEnum):
    submit_code = 0
    run_test = 1
    update_code = 2
    get_code = 3

class MessageSendID(IntEnum):
    game_info = 0
    submission_info = 1
    error_message = 2
    test_results = 3
    game_end = 4

class GameState(IntEnum):
    in_progress = 1
    finishing = 2
    finished = 3

class Language:
    languages: ClassVar[dict[str, Language]] = {}

    name: str
    version: str
    aliases: list[str]
    runtime: str

    @classmethod
    def class_init(cls):
        languages: dict[str, dict] = piston.languages

        for lang_name, lang_infos in languages.items():
            lang_version = lang_infos["version"]
            lang_aliases = lang_infos["aliases"]
            lang_runtime = lang_infos.get("runtime", "")

            if not (
                type(lang_name) is str and
                type(lang_version) is str and
                type(lang_runtime) is str and
                type(lang_aliases) is list and
                all(type(alias) is str
                    for alias in lang_aliases)):
                raise TypeError("Piston API: wrong response type")

            language = cls(lang_name, lang_version, lang_aliases, lang_runtime)
            cls.languages[language.name] = language

    def __init__(self, name: str, version: str, aliases: list[str], runtime: str) -> None:
        self.name = name
        self.version = version
        self.aliases = aliases
        self.runtime = runtime

    def as_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "aliases": self.aliases,
            "runtime": self.runtime
        }

    @classmethod
    def get(cls, name: str):
        return cls.languages[name]

Language.class_init()

class Submission:
    code: str
    language: Language
    success: list[bool]
    state: SubmissionState
    finished_time: float

    def __init__(self) -> None:
        self.code = ""
        self.success = []
        self.state = SubmissionState.in_progess
        self.finished_time = 0.

    def as_dict(self):
        return {
            "code_length": len(self.code),
            "language": Language.name,
            "success": self.success,
            "state": self.state.name,
            "finished_time": self.finished_time
        }

class Validator:
    input: str
    output: str

    def __init__(self, input: str, output: str) -> None:
        self.input = input
        self.output = output

    def execute(self, code: str, language: Language, retry_limit: int = 2) -> tuple[bool, str]:
        """
            returns (success: bool, output: str)
            This function is blocking, so everything will stop working until the code finishes executing!!
        """
        # TODO: add languages!!
        lang_name = language.name
        lang_version = language.version
        validator_input = self.input
        validator_output = self.output.rstrip("\n")
        for _ in range(retry_limit):
            try:
                output: str = piston.execute(
                    lang_name, lang_version, code, validator_input, timeout=100)
                return (output.rstrip("\n") == validator_output, output)
            except PistonError:
                continue

        return False, "Internal error"

class Puzzle:
    title: str
    statement: str
    testcases: list[Validator]
    validators: list[Validator]

    puzzles: list[Puzzle] = []

    def __init__(self, title: str, statement: str, validators: list[Validator], testcases: list[Validator]) -> None:
        self.title = title
        self.statement = statement
        self.validators = validators
        self.testcases = testcases

        Puzzle.puzzles.append(self)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "statement": self.statement,
            "testcases": self.testcases
            }

class Game:
    players: ClassVar[list[Player]] = []
    submissions: ClassVar[dict[Player, Submission]] = {}
    puzzle: ClassVar[Puzzle]
    duration_between_games: ClassVar[int] = 60
    duration: ClassVar[int] = 600
    start_time: ClassVar[int]
    end_time: ClassVar[int]
    state: ClassVar[GameState]

    @classmethod
    async def game_loop(cls):
        # Put random puzzle as the previous puzzle although there is no previous puzzle!
        cls.puzzle = choice(Puzzle.puzzles)

        while 1:
            # First game shouldn't instantly start
            # that's why we have this order
            cls.state = GameState.finished
            cls.start_time = int(time() + cls.duration_between_games)
            cls.end_time = int(cls.start_time + cls.duration)
            await cls.broadcast({"id": MessageSendID.game_end, "time_until_next_game": cls.start_time})
            await asyncio.sleep(cls.duration_between_games)
            
            cls.state = GameState.in_progress
            cls.submissions = {player: Submission() for player in cls.players}
            cls.puzzle = choice(Puzzle.puzzles)
            await cls.broadcast({cls.game_info_message()})
            await asyncio.sleep(cls.end_time - time() + 3) # 3 extra seconds For communication delay :p

            cls.state = GameState.finishing
            for player, submission in cls.submissions.items():
                if submission.state is not SubmissionState.in_progess:
                    await cls.submit_code(player)
            

    @classmethod
    async def join(cls, player: Player):
        if any(player_.nickname == player.nickname for player_ in cls.submissions):
            await player.send_error("Nickname was taken")
            raise ValueError

        cls.players.append(player)
        cls.submissions[player] = Submission()
        await player.send(cls.game_info_message())

    @classmethod
    async def game_info_message(cls):
        return {
            "id": MessageSendID.game_info, 
            "submissions": {player.nickname: submission.as_dict() for player, submission in cls.submissions.items()},
            "puzzle": cls.puzzle.as_dict(),
            "end_time": cls.end_time,
            "delay_between_games": cls.duration_between_games,
            "available_languages": [language.as_dict() for language in Language.languages.values()]
        }

    @classmethod
    async def leave(cls, player: Player):
        cls.players.remove(player)

    @classmethod
    async def submit_code(cls, player: Player):
        # TODO: put this in submission? who cares!
        submission = cls.submissions[player]
        if submission.state is not SubmissionState.in_progess:
            raise SessionException("Can't submit: Already submitted!")

        submission.finished_time = time()
        submission.state = SubmissionState.pending
        await cls.broadcast({"id": MessageSendID.submission_info, "player": player.nickname, "submission": submission.as_dict()})

        for validator in cls.puzzle.validators:
            success, output = validator.execute(submission.code, submission.language)
            submission.success.append(success)
        submission.state = SubmissionState.finished
        await cls.broadcast({"id": MessageSendID.submission_info, "player": player.nickname, "submission": submission.as_dict()})

    @classmethod
    async def run_test(cls, player: Player):
        # TODO: put this in submission.

        results = []
        submission = cls.submissions[player]
        for validator in cls.puzzle.testcases:
            success, output = validator.execute(submission.code, submission.language)
            results.append(success)
        await player.send({"id":MessageSendID.test_results, "success": results})

    @classmethod
    async def update_code(cls, player: Player, code: str, language: Language):
        if Game.state is not GameState.in_progress:
            raise SessionException("Can't test code: Game already ended")

        cls.submissions[player].code = code
        cls.submissions[player].language = language

    @classmethod
    async def get_code(cls, player: Player, submission_owner_nickname: str):
        if cls.submissions[player].state is SubmissionState.in_progess:
            raise SessionException("Can't get code: You need to submit first")

        for player_, submission in cls.submissions.items():
            if player_.nickname == submission_owner_nickname:
                return submission.code

        raise SessionException("Can't get code: No player with such nickname")

    @classmethod
    async def broadcast(cls, message: object):
        for player in cls.players:
            await player.send(message)


class SessionException(Exception):
    pass

class Player:
    ws: WebsocketImplProtocol
    nickname: str
    
    def __init__(self, ws: WebsocketImplProtocol):
        self.ws = ws
        asyncio.run(self.__auth())
        
    async def __auth(self):
        message = await self.recv()
        if message.keys() != {"nickname"}:
            await self.send_error("Wrong message structure")
            raise ValueError

        self.nickname = message["nickname"]
        await Game.join(self)

    async def recv(self) -> dict[str,Any]: #type: ignore
        message = await self.ws.recv(10)
        assert message is not None
        message_dict = json.loads(message)

        if not isinstance(message_dict,dict):
            raise SessionException("Wrong message structure")

        return message_dict

    async def send(self, message: object):
        await self.send(json.dumps(message))

    async def send_error(self, error_messege: str):
        await self.send({"id":MessageSendID.error_message, "error": error_messege})

    async def ws_handler(self):
        try:
            while 1:
                try:
                    message = await self.recv()

                    if message["id"] is MessageRecvID.submit_code:
                        if message.keys() != {"id", "code", "language"}:
                            raise SessionException("Wrong message structure")

                        if Game.state is not GameState.in_progress:
                            raise SessionException("Can't submit: Game is already ended")

                        await Game.update_code(self, message["code"], Language.get(message["language"]))
                        await Game.submit_code(self)

                    elif message["id"] is MessageRecvID.run_test:
                        if message.keys() != {"id", "code", "language"}:
                            raise SessionException("Wrong message structure")
                            
                        await Game.update_code(self, message["code"], Language.get(message["language"]))
                        await Game.run_test(self)

                    elif message["id"] is MessageRecvID.update_code:
                        if message.keys() != {"id", "code", "language"}:
                            raise SessionException("Wrong message structure")
                        
                        await Game.update_code(self, message["code"], Language.get(message["language"]))

                    elif message["id"] is MessageRecvID.get_code:
                        if message.keys() != {"id", "player_nickname"}:
                            raise SessionException("Wrong message struture")

                        await Game.get_code(self, message["player_nickname"])

                except SessionException as e:
                    await self.send_error(str(e))

        except Exception as e:
            # XXX: LOG ?
            pass
        finally:
            await Game.leave(self)



def start():
    if app.state.stage is not ServerStage.STOPPED:
        raise Exception("App is already running!")

    print("GameCodin is running on http://localhost:8080/")
    loop = asyncio.get_event_loop()
    loop.create_task(Game.game_loop())
    app.run(host="0.0.0.0", port=8080, workers=1, debug=True, verbosity=1, access_log=False)

if __name__ == "__main__":
    start()