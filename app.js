async function submitForm() {
  const documentUrl = document.getElementById("documentUrlInput").value;
  const questionsText = document.getElementById("questionInput").value;
  const responseBox = document.getElementById("responseBox");

  if (!documentUrl || !questionsText) {
    alert("Please enter a document URL and your questions.");
    return;
  }

  let timer = 0;
  let timerInterval = null;

  function updateTimer() {
    const timerElem = document.getElementById('timerSpan');
    if (timerElem) timerElem.textContent = timer + 's';
  }

  responseBox.innerHTML = `<span class="loader"></span> <span>Thinking... Please wait while we analyze your document and questions. <span id='timerSpan'>0s</span></span>`;
  timer = 0;
  timerInterval = setInterval(() => {
    timer++;
    updateTimer();
  }, 1000);

  let waitingTimeout = setTimeout(() => {
    responseBox.innerHTML = `<span class="loader"></span> <span>Still working... This may take a few more seconds for large documents or complex questions.<br><span class='waiting-msg'>Thank you for your patience!</span> <span id='timerSpan'>${timer}s</span></span>`;
    updateTimer();
  }, 5000);

  try {
    const questions = questionsText.split(",").map(q => q.trim()).filter(q => q);

    const queryRes = await fetch("/hackrx/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer hackrx-secret-token",
        "Accept": "application/json"
      },
      body: JSON.stringify({
        documents: documentUrl,
        questions: questions
      })
    });

    if (!queryRes.ok) {
      throw new Error(`Query failed: ${await queryRes.text()}`);
    }

    const data = await queryRes.json();
    clearTimeout(waitingTimeout);
    clearInterval(timerInterval);
    responseBox.innerHTML = `<div style="margin-bottom:8px;color:var(--accent);font-size:0.98em;">⏱️ Answer loaded in <b>${timer}s</b></div><pre>${JSON.stringify(data, null, 2)}</pre>`;

  } catch (err) {
    console.error(err);
    clearTimeout(waitingTimeout);
    clearInterval(timerInterval);
    if (err instanceof TypeError && err.message.includes("Failed to fetch")) {
      responseBox.innerHTML = `<b style="color:red">❌ Error:</b> Could not connect to backend server.`;
    } else {
      responseBox.innerHTML = `<b style="color:red">❌ Error:</b> ${err.message}`;
    }
  }
}
