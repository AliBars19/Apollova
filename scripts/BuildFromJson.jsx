// -------------------------------------------------------
// AUTO BUILD FROM JSON - MV
// -------------------------------------------------------

function importJobData() {
    var jsonFile = File.openDialog("Select your job_data.json file", "*.json");
    if (!jsonFile) return null;

    jsonFile.open("r");
    var jsonText = jsonFile.read();
    jsonFile.close();

    try {
        return JSON.parse(jsonText);
    } catch (e) {
        alert("Error parsing JSON: " + e.toString());
        return null;
    }
}

// -------------------------------------------------------
// MAIN SCRIPT
// -------------------------------------------------------

function main() {
    app.beginUndoGroup("Auto Music Video Build");

    // ------------------ Phase 1: Import & setup ------------------
    var job = importJobData();
    if (!job) {
        alert("No JSON data found.");
        return;
    }

    // Paths from JSON
    var audioFile = new File(job.audio_trimmed);
    var imageFile = new File(job.cover_image);
    var lyricsFile = new File(job.lyrics_file);
    var colors = job.colors;

    // Import audio and image
    var audioItem = app.project.importFile(new ImportOptions(audioFile));
    var imageItem = app.project.importFile(new ImportOptions(imageFile));

    // Locate your main template comp
    var templateComp = null;
    for (var i = 1; i <= app.project.numItems; i++) {
        if (app.project.item(i).name === "3D Apple Music") {
            templateComp = app.project.item(i);
            break;
        }
    }
    if (!templateComp) {
        alert("Template comp '3D Apple Music' not found!");
        return;
    }

    // Duplicate the template comp for the new job
    var newComp = templateComp.duplicate();
    newComp.name = "MV_JOB_" + job.job_id;

    // Replace placeholders
    replaceLayer(newComp, "AUDIO", audioItem);
    replaceLayer(newComp, "COVER", imageItem);

    // Apply colors to gradient or background layers
    updateBackgroundColors(newComp, colors);

    // ------------------ Phase 2: Lyrics + Markers ------------------
    var outputComp = findCompByName("OUTPUT 1");
    var lyricComp = findPrecompLayer(outputComp, "LYRIC FONT 1");

    var parsed = parseLyricsFile(job.lyrics_file);
    pushLyricsToCarousel(lyricComp, parsed.linesArray);
    setAudioMarkersFromTArray(lyricComp, parsed.tAndText);

    app.endUndoGroup();
    alert("✅ Build complete for Job " + job.job_id + " with lyrics + markers!");
}

// -------------------------------------------------------
// HELPER FUNCTIONS
// -------------------------------------------------------

function replaceLayer(comp, layerName, newItem) {
    for (var i = 1; i <= comp.numLayers; i++) {
        if (comp.layer(i).name === layerName) {
            comp.layer(i).replaceSource(newItem, false);
            return;
        }
    }
}

function updateBackgroundColors(comp, colors) {
    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (lyr.property("Effects") && lyr.property("Effects")("4-Color Gradient")) {
            var effect = lyr.property("Effects")("4-Color Gradient");
            for (var j = 0; j < colors.length; j++) {
                var aeColor = hexToRGB(colors[j]);
                effect.property("Color " + (j + 1)).setValue(aeColor);
            }
        }
    }
}

function hexToRGB(hex) {
    hex = hex.replace("#", "");
    var r = parseInt(hex.substring(0, 2), 16) / 255;
    var g = parseInt(hex.substring(2, 4), 16) / 255;
    var b = parseInt(hex.substring(4, 6), 16) / 255;
    return [r, g, b];
}

// -------------------------------------------------------
// --- Phase 2 helpers: lyrics + markers ------------------
// -------------------------------------------------------

function readTextFile(absPath) {
    var f = new File(absPath);
    if (!f.exists) throw new Error("File not found: " + absPath);
    f.open("r");
    var txt = f.read();
    f.close();
    return txt;
}

function findCompByName(name) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof CompItem && it.name === name) return it;
    }
    throw new Error("Comp not found: " + name);
}

function findPrecompLayer(comp, layerName) {
    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (lyr instanceof AVLayer && lyr.source instanceof CompItem && lyr.name === layerName) {
            return lyr.source;
        }
    }
    throw new Error("Precomp layer not found in " + comp.name + ": " + layerName);
}

function replaceLyricArrayInLayer(layer, linesArray) {
    var pieces = [];
    for (var i = 0; i < linesArray.length; i++) {
        var s = String(linesArray[i])
            .replace(/\\/g, "\\\\")
            .replace(/"/g, '\\"');
        pieces.push('"' + s + '"');
    }
    var newArrayBlock = "var lyrics = [\n" + pieces.join(",\n") + "\n];";

    var prop = layer.property("Source Text");
    if (!prop.canSetExpression) return;
    var expr = prop.expression;

    var regex = /var\s+lyrics\s*=\s*\[[\s\S]*?\];/;
    expr = regex.test(expr)
        ? expr.replace(regex, newArrayBlock)
        : newArrayBlock + "\n" + expr;

    prop.expression = expr;
}

function pushLyricsToCarousel(lyricComp, linesArray) {
    var targets = ["LYRIC PREVIOUS", "LYRIC CURRENT", "LYRIC NEXT 1", "LYRIC NEXT 2"];
    for (var i = 0; i < targets.length; i++) {
        var lyr = lyricComp.layer(targets[i]);
        if (!lyr) throw new Error("Missing lyric layer: " + targets[i]);
        replaceLyricArrayInLayer(lyr, linesArray);
    }
}

function clearAllMarkers(layer) {
    var mk = layer.property("Marker");
    if (!mk) return;
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);
}

function setAudioMarkersFromTArray(lyricComp, tAndText) {
    var audio = lyricComp.layer("AUDIO");
    if (!audio) throw new Error("Missing 'AUDIO' layer in " + lyricComp.name);

    var mk = audio.property("Marker");
    if (!mk) throw new Error("No Marker property on AUDIO");

    clearAllMarkers(audio);

    var lastT = 0;
    for (var i = 0; i < tAndText.length; i++) {
        var t = Number(tAndText[i].t);
        var name = String(tAndText[i].cur || "LYRIC_" + (i + 1));
        var mv = new MarkerValue(name);
        mk.setValueAtTime(t, mv);
        if (t > lastT) lastT = t;
    }

    var tail = 2;
    if (lastT + tail > lyricComp.duration) lyricComp.duration = lastT + tail;
}

function parseLyricsFile(absPath) {
    var raw = readTextFile(absPath);
    var data = JSON.parse(raw);
    var linesArray = [];
    var tAndText = [];

    for (var i = 0; i < data.length; i++) {
        var cur = String(data[i].lyric_current || data[i].cur || "");
        linesArray.push(cur);
        tAndText.push({ t: Number(data[i].t || 0), cur: cur });
    }
    return { linesArray: linesArray, tAndText: tAndText };
}

// -------------------------------------------------------
main();
