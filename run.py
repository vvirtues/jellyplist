from app import app, socketio

if __name__ == '__main__':
    #app.run(debug=True, port=5001,host="0.0.0.0")
    socketio.run(app,host="0.0.0.0", port = 5055)
