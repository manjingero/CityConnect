$(document).ready(function(){
  var socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
  var currentRoom = '';
  var username = '';
  var currentTurn = '';
  var modalX = null, modalY = null;

  // Global zoom level for grid scaling; default is 1 (100%).
  var zoomLevel = 1;

  // Zoom control event handlers.
  $("#zoom-in").click(function(){
    zoomLevel += 0.1;
    applyZoom();
  });
  $("#zoom-out").click(function(){
    if(zoomLevel > 0.6) { // minimum zoom level: 60%
      zoomLevel -= 0.1;
      applyZoom();
    }
  });
  $("#zoom-home").click(function(){
    zoomLevel = 1;
    applyZoom();
  });

  function applyZoom(){
    // Apply the scale transform to #grid-content.
    $("#grid-content").css("transform", "scale(" + zoomLevel + ")");

    // Determine the scaled dimensions.
    var gridFrameWidth = $("#game-grid").width();
    var gridFrameHeight = $("#game-grid").height();
    var contentWidth = $("#grid-content").outerWidth();
    var contentHeight = $("#grid-content").outerHeight();
    var scaledWidth = contentWidth * zoomLevel;
    var scaledHeight = contentHeight * zoomLevel;

    // Center the content if it's smaller than the frame;
    // otherwise, do not force centering (allow scrolling).
    var left = 0, top = 0;
    if(scaledWidth < gridFrameWidth) {
      left = (gridFrameWidth - scaledWidth) / 2;
    }
    if(scaledHeight < gridFrameHeight) {
      top = (gridFrameHeight - scaledHeight) / 2;
    }
    $("#grid-content").css({ position: "absolute", left: left + "px", top: top + "px" });
  }

  // Fetch public games list.
  function fetchPublicGames(){
    $.getJSON('./public_games', function(data){
      var listDiv = $("#public-games-list");
      listDiv.empty();
      if(data.length === 0){
        listDiv.append("<p>No active games at the moment.</p>");
      } else {
        data.forEach(function(game){
          var card = $("<div class='card mb-2'></div>");
          var cardBody = $("<div class='card-body'></div>");
          cardBody.append("<h5 class='card-title'>Room: " + game.room + "</h5>");
          cardBody.append("<p class='card-text'>Starting City: " + game.starting_city + "</p>");
          cardBody.append("<p class='card-text'>Players: " + game.players.join(', ') + "</p>");
          var joinBtn = $("<button class='btn btn-secondary join-game' data-room='" + game.room + "'>Join Game</button>");
          cardBody.append(joinBtn);
          card.append(cardBody);
          listDiv.append(card);
        });
      }
    });
  }

  setInterval(fetchPublicGames, 5000);
  fetchPublicGames();

  // Create Game event.
  $("#create-game").click(function(){
    username = $("#create-username").val().trim();
    var room = $("#create-room").val().trim();
    if(username === ""){
      $("#lobby-message").text("Please enter a username.");
      return;
    }
    if(room === ""){
      room = "Room_" + Math.floor(Math.random()*10000);
    }
    socket.emit('enter_room', {room: room, username: username});
  });

  // Join Game event.
  $(document).on("click", ".join-game", function(){
    var room = $(this).data("room");
    var user = prompt("Enter your username:");
    if(user === null || user.trim() === ""){
      alert("Username is required.");
      return;
    }
    username = user.trim();
    socket.emit('enter_room', {room: room, username: username});
  });

  // Handle errors from the server.
  socket.on('error', function(data){
    $("#lobby-message").text(data.message);
    alert("Error: " + data.message);
  });

  // Room update event.
  socket.on('room_update', function(data){
    currentRoom = data.room;
    currentTurn = data.current_turn;
    $("#current-room").text(data.room);
    $("#starting-city").text(data.starting_city);
    $("#players-list").text(data.players.join(', '));
    $("#current-turn").text(data.current_turn);
    updateLeaderboard(data.leaderboard);
    $("#lobby-section").hide();
    $("#game-section").show();
    // Reset zoom on new room join.
    zoomLevel = 1;
    renderGrid(data.grid, data.expansion);
  });

  // Move made event.
  socket.on('move_made', function(data){
    currentTurn = data.current_turn;
    $("#current-turn").text(data.current_turn);
    updateLeaderboard(data.leaderboard);
    renderGrid(data.grid, data.expansion);
  });

  // Render the board.
  function renderGrid(gridData, expansion){
    // Reset zoom and content.
    $("#grid-content").empty();
    $("#grid-content").css("transform", "scale(1)");
    zoomLevel = 1;

    var xs = [], ys = [];
    for(var key in gridData){
      var coords = key.replace('(', '').replace(')', '').split(',');
      var x = parseInt(coords[0]);
      var y = parseInt(coords[1]);
      xs.push(x);
      ys.push(y);
    }
    if(xs.length === 0){ xs.push(0); }
    if(ys.length === 0){ ys.push(0); }
    var minX = Math.min.apply(null, xs);
    var maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys);
    var maxY = Math.max.apply(null, ys);
    var width = Math.max(10, maxX - minX + 1);
    var height = Math.max(10, maxY - minY + 1);
    width += expansion;
    height += expansion;
    var centerX = (minX + maxX) / 2;
    var centerY = (minY + maxY) / 2;
    var startX = Math.floor(centerX - width/2);
    var startY = Math.floor(centerY - height/2);

    var gridContent = $("#grid-content");
    var cellSize = 50;
    gridContent.css({ width: (width * cellSize) + "px", height: (height * cellSize) + "px" });

    for(var i = 0; i < width; i++){
      for(var j = 0; j < height; j++){
        var cellX = startX + i;
        var cellY = startY + j;
        var key = "(" + cellX + ", " + cellY + ")";
        var letter = gridData[key] || "";
        var cell = $("<div class='grid-cell'></div>");
        cell.css({ left: i * cellSize + "px", top: j * cellSize + "px" });
        cell.text(letter);
        cell.data("coord", { x: cellX, y: cellY, letter: letter });
        cell.on("click", function(e){
          if(currentTurn !== username){
            alert("Wait for your turn.");
            return;
          }
          var coord = $(this).data("coord");
          openMoveModal(coord.x, coord.y, coord.letter);
        });
        gridContent.append(cell);
      }
    }
    applyZoom();
  }

  // Update the leaderboard display.
  function updateLeaderboard(leaderboard) {
    var list = $("#leaderboard-desktop");
    list.empty();
    leaderboard.forEach(function(item){
      var listItem = $("<li></li>");
      if(item.name !== "User Left" && item.name === username) {
        listItem.css("font-weight", "bold");
      }
      listItem.text(item.name + " - " + item.score);
      list.append(listItem);
    });
  }

  // Open the move modal.
  function openMoveModal(x, y, letter){
    $("#modal-error").text("");
    $("#modal-info").text("Selected cell (" + x + ", " + y + "). " +
      "If empty, your move must intersect an existing letter along its path.");
    $("#city-input").val("");
    $("#direction-select").val("down");
    $("#moveModal").modal("show");
    modalX = x;
    modalY = y;
  }

  // Submit move.
  $("#modal-submit").click(function(){
    var direction = $("#direction-select").val();
    var city = $("#city-input").val().trim();
    if(city === ""){
      $("#modal-error").text("Please enter a city name.");
      return;
    }
    $("#moveModal").modal("hide");
    socket.emit('new_move', {
      room: currentRoom,
      username: username,
      x: modalX,
      y: modalY,
      direction: direction,
      city: city
    });
  });

  $("#modal-cancel").click(function(){
    $("#moveModal").modal("hide");
  });
});