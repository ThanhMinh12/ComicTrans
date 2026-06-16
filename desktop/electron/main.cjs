const { app, BrowserWindow } = require("electron");
const path = require("path");

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1120,
    minHeight: 740,
    title: "ComicTrans",
    backgroundColor: "#f4f6f7",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (app.isPackaged) {
    window.loadFile(path.join(__dirname, "../dist/index.html"));
  } else {
    window.loadURL(process.env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173");
  }
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
