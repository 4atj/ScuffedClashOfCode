// Ah should change those enums to PASCAL CASE in both python and js
// But who cares, lets leave them like this.

MessageSendID = {
    submit_code: 0,
    run_test: 1,
    update_code: 2,
    get_submission_code: 3,
}

MessageRecvID = {
    game_info: 0,
    submission_info: 1,
    submission_code: 2,
    test_results: 3,
    game_end: 4,
    error_message: 5
}

SubmissionState = {
    in_progess: 0,
    pending: 1,
    finished: 2
}

GameState = {
    in_progess: 0,
    pending: 1,
    finished: 2
}

class Game {
    static submissions = {};
    static languages = {};
    static state;
    static start_time;
    static end_time;
    static puzzle;
}

class Session {
    static ws = null;
    static connenct() {
        if (this.ws !== null && (
            this.ws.readyState === WebSocket.OPEN ||
            this.ws.readyState === WebSocket.CONNECTING))
            
            this.ws.close();            
        
        this.ws = new WebSocket("ws://127.0.0.1:8080");

        WebSocket.addEventListener('open', (event) => {
            this.ws.send({nickname: "Murat", token: "We need to set this in cookies"});
            // send the handshake packet here
        });
    

        WebSocket.addEventListener('message', (event) => {
            let message = JSON.parse(event.data);
            console.log("recieved a message",message);
            switch (message.id) {
                case MessageRecvID.game_info:
                    Game.languages = message.available_languages,
                    Game.start_time = message.start_time,
                    Game.end_time = message.end_time,
                    Game.state = message.state,    
                    Game.submissions = message.submissions,
                    Game.puzzle = message.puzzle;
                    // Start game / Reset game
                    break;
                    
                case MessageRecvID.submission_info:
                    let player_nickname = message.player_nickname,
                        submission = message.submission;

                    Game.submissions[player_nickname] = submission;
                    // Update submissions list
                    break;

                case MessageRecvID.submission_code:
                    let code = message.submission;
                    player_nickname = message.player_nickname;

                    Game.submissions[player_nickname].code = code;
                    
                    // Update submissions list
                    break;

                case MessageRecvID.test_results:
                    let results = message.results;
                    // update testcases success
                    break;

                case MessageRecvID.game_end:
                    Game.start_time = message.next_game_start_time;
                    // update timer
                    break;

                case MessageRecvID.error_message:
                    let error_message = error_message;
                    // display the error
                    break;

                default:
                    console.error("SOMETHING IS WRONG MONKAS!");
                    break;
            }
        });
        
        WebSocket.addEventListener('close', (event) => {
            this.ws = null;
            // Comeback to the joining page
        });
    }
}


// connect after clicking a connect button?
Session.connenct();