async function sendMessage(){
    const message = document.getElementById("messageInput").value;
    const responseDiv = document.getElementById("response");

    const res=await fetch("/chat",{
        method: "POST",
        headers:{
            "Content-Type": "application/json"
        },
        body: JSON.stringify({message})
    });
    const data = await res.json();
    responseDiv.innerText = data.response;
}