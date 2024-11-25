from flask import Flask, request, jsonify,render_template,url_for,session,redirect


app = Flask(__name__)
app.secret_key= 'hello'

@app.route('/',methods=['GET', 'POST'])
def homepage():
    if request.method =='POST':
        session["username"]=request.form.get("username")
        #session["password"]=request.form.get("password")
        username=session['username']

        return render_template("index.html",username=username)
    else:
        return redirect( url_for('login') )
    

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method=='POST':
        #return render_template("index.html")
        return redirect(url_for('homepage'))
    else:
        return render_template('login.html')
    


@app.route('/start-session')
def start_session():
    

    
"""
@app.route('/submit', methods=['POST'])
def submit_data():
    
    name = request.form.get('name','unknown')  
    session['name']=name
    age = request.form.get('age',0)          
    session['age']=age

    username=session['name']
    
    return render_template("submit.html",username=username)"""

if __name__ == "__main__":
    app.run( port=5000,debug=True)
