// ===============================
// VISUALS NOVA - After Effects Automation
// Batch process 12 jobs with word-level markers
// ===============================

(function() {
    
    // Configuration
    var TOTAL_JOBS = 12;
    var JOBS_DIR = "jobs/";
    var COMP_NAME_PREFIX = "NOVA_";
    var FRAME_RATE = 30;
    var DURATION_SECONDS = 61; // Default duration
    
    // ===============================
    // MAIN
    // ===============================
    
    app.beginUndoGroup("NOVA Batch Process");
    
    try {
        for (var jobId = 1; jobId <= TOTAL_JOBS; jobId++) {
            processNovaJob(jobId);
        }
        alert("✓ NOVA batch processing complete!\n\n" + TOTAL_JOBS + " videos generated.");
    } catch(e) {
        alert("Error: " + e.toString());
    }
    
    app.endUndoGroup();
    
    // ===============================
    // PROCESS SINGLE JOB
    // ===============================
    
    function processNovaJob(jobId) {
        var jobFolder = JOBS_DIR + "job_" + padZero(jobId, 3) + "/";
        var dataPath = jobFolder + "nova_data.json";
        
        // Read job data
        var jobData = readJSON(dataPath);
        if (!jobData) {
            alert("Missing nova_data.json for job " + jobId);
            return;
        }
        
        var songTitle = jobData.song_title || "Unknown";
        var markers = jobData.markers || [];
        
        // Create comp
        var compName = COMP_NAME_PREFIX + padZero(jobId, 3);
        var comp = app.project.items.addComp(compName, 1080, 1920, 1, DURATION_SECONDS, FRAME_RATE);
        
        // Import audio
        var audioFile = new File(jobFolder + "audio_trimmed.wav");
        if (!audioFile.exists) {
            alert("Audio file not found: " + audioFile.fsName);
            return;
        }
        
        var audioItem = app.project.importFile(new ImportOptions(audioFile));
        var audioLayer = comp.layers.add(audioItem);
        audioLayer.name = "AUDIO";
        
        // Add markers to audio layer
        addMarkersToLayer(audioLayer, markers);
        
        // Create background solid (will flip color via expression)
        var bgLayer = comp.layers.addSolid([1, 1, 1], "BACKGROUND", 1080, 1920, 1, DURATION_SECONDS);
        bgLayer.moveToEnd();
        
        // Apply color flip expression to background
        var bgColorProp = bgLayer.property("ADBE Effect Parade").addProperty("ADBE Fill");
        var bgColorControl = bgColorProp.property("ADBE Fill-0002");
        bgColorControl.expression = getColorFlipExpression();
        
        // Create text layer
        var textLayer = comp.layers.addText("");
        textLayer.name = "LYRIC_TEXT";
        
        // Style text (Brat font aesthetic)
        var textProp = textLayer.property("ADBE Text Properties").property("ADBE Text Document");
        var textDoc = textProp.value;
        textDoc.fontSize = 72;
        textDoc.font = "ArialMT"; // Use Arial Bold in practice
        textDoc.fillColor = [1, 1, 1]; // Will be controlled by expression
        textDoc.justification = ParagraphJustification.CENTER_JUSTIFY;
        textDoc.applyStroke = false;
        textProp.setValue(textDoc);
        
        // Apply word-by-word reveal expression
        var sourceTextProp = textLayer.property("ADBE Text Properties").property("ADBE Text Document");
        sourceTextProp.expression = getWordRevealExpression();
        
        // Apply color flip to text fill
        var textFillProp = textLayer.property("ADBE Text Properties").property("ADBE Text Animators").addProperty("ADBE Text Animator");
        textFillProp.name = "Color Flip";
        var fillColorProp = textFillProp.property("ADBE Text Animator Properties").addProperty("ADBE Text Fill Color");
        fillColorProp.property("ADBE Text Fill Color").expression = getColorFlipExpression();
        
        // Position text center
        var textPosition = textLayer.property("ADBE Transform Group").property("ADBE Position");
        textPosition.setValue([540, 960]);
        
        // Add to render queue
        var renderItem = app.project.renderQueue.items.add(comp);
        renderItem.outputModule(1).file = new File(jobFolder + compName + ".mp4");
    }
    
    // ===============================
    // ADD MARKERS
    // ===============================
    
    function addMarkersToLayer(layer, markers) {
        var markerProp = layer.property("ADBE Marker");
        
        for (var i = 0; i < markers.length; i++) {
            var m = markers[i];
            var markerTime = m.time;
            var markerComment = m.comment;
            
            var newMarker = new MarkerValue(markerComment);
            markerProp.setValueAtTime(markerTime, newMarker);
        }
    }
    
    // ===============================
    // EXPRESSIONS
    // ===============================
    
    function getWordRevealExpression() {
        return [
            "var audio = thisComp.layer(\"AUDIO\");",
            "var m = audio.marker;",
            "",
            "if (m.numKeys === 0) {",
            "    \"\";",
            "} else {",
            "    var t = time;",
            "    var idx = 0;",
            "",
            "    for (var k = 1; k <= m.numKeys; k++) {",
            "        if (t >= m.key(k).time) idx = k;",
            "        else break;",
            "    }",
            "",
            "    if (idx === 0) {",
            "        \"\";",
            "    } else {",
            "        var markerData;",
            "        try {",
            "            markerData = JSON.parse(m.key(idx).comment);",
            "        } catch(e) {",
            "            m.key(idx).comment;",
            "        }",
            "",
            "        if (!markerData || !markerData.words || markerData.words.length === 0) {",
            "            markerData.text || m.key(idx).comment;",
            "        } else {",
            "            var words = markerData.words;",
            "            var output = \"\";",
            "            ",
            "            for (var i = 0; i < words.length; i++) {",
            "                var word = words[i];",
            "                ",
            "                if (t >= word.start) {",
            "                    output += word.word;",
            "                    if (i < words.length - 1) output += \" \";",
            "                } else {",
            "                    break;",
            "                }",
            "            }",
            "            ",
            "            output;",
            "        }",
            "    }",
            "}"
        ].join("\n");
    }
    
    function getColorFlipExpression() {
        return [
            "var audio = thisComp.layer(\"AUDIO\");",
            "var m = audio.marker;",
            "",
            "if (m.numKeys === 0) {",
            "    [1, 1, 1, 1];",
            "} else {",
            "    var t = time;",
            "    var idx = 0;",
            "",
            "    for (var k = 1; k <= m.numKeys; k++) {",
            "        if (t >= m.key(k).time) idx = k;",
            "        else break;",
            "    }",
            "",
            "    if (idx === 0) {",
            "        [1, 1, 1, 1];",
            "    } else {",
            "        var markerData;",
            "        try {",
            "            markerData = JSON.parse(m.key(idx).comment);",
            "        } catch(e) {",
            "            markerData = { color: (idx % 2 === 1) ? \"white\" : \"black\" };",
            "        }",
            "",
            "        if (markerData.color === \"black\") {",
            "            [0, 0, 0, 1];",
            "        } else {",
            "            [1, 1, 1, 1];",
            "        }",
            "    }",
            "}"
        ].join("\n");
    }
    
    // ===============================
    // HELPERS
    // ===============================
    
    function readJSON(filePath) {
        var file = new File(filePath);
        if (!file.exists) return null;
        
        file.open("r");
        var content = file.read();
        file.close();
        
        return eval("(" + content + ")");
    }
    
    function padZero(num, size) {
        var s = num + "";
        while (s.length < size) s = "0" + s;
        return s;
    }
    
})();