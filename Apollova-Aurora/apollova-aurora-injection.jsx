// -------------------------------------------------------
// FULL AUTOMATION PIPELINE - PHASE 1–6
// Batch Music Video Builder + Renderer (FINAL FIXED)
// -------------------------------------------------------
// Usage:
//  1) Run main.py to build /jobs/job_001 → job_012
//  2) Open AE project with folders Foreground, Background,
//     OUTPUT1–OUTPUT12, and comps MAIN, LYRIC FONT N, Assets N, etc.
//  3) File → Scripts → Run Script File → select this file
//  4) Pick the /jobs folder → items import + comps wired + queued
// -------------------------------------------------------

// -----------------------------
// JSON Polyfill (for older AE)
// -----------------------------
if (typeof JSON === "undefined") {
    JSON = {};
    JSON.parse = function (s) {
        try { return eval("(" + s + ")"); }
        catch (e) { alert("Error parsing JSON: " + e.toString()); return null; }
    };
    JSON.stringify = function (obj) {
        var t = typeof obj;
        if (t !== "object" || obj === null) {
            if (t === "string") obj = '"' + obj + '"';
            return String(obj);
        } else {
            var n, v, json = [], arr = (obj && obj.constructor === Array);
            for (n in obj) {
                v = obj[n];
                t = typeof v;
                if (t === "string") v = '"' + v + '"';
                else if (t === "object" && v !== null) v = JSON.stringify(v);
                json.push((arr ? "" : '"' + n + '":') + String(v));
            }
            return (arr ? "[" : "{") + String(json) + (arr ? "]" : "}");
        }
    };
}


// -----------------------------
// INJECTED PATHS (replaced by GUI)
// -----------------------------
var JOBS_PATH = "{{JOBS_PATH}}";
var TEMPLATE_PATH = "{{TEMPLATE_PATH}}";
var AUTO_RENDER = "{{AUTO_RENDER}}";

// -----------------------------
// LYRIC FORMATTING CONSTANTS
// -----------------------------
var MAX_CHARS_PER_LINE = 30;  // Wrap to 2 lines above this char count (matches Mono/Onyx behaviour)

// -----------------------------
// MAIN
// -----------------------------
function main() {
    // First, open the template project if path was injected
    if (TEMPLATE_PATH.indexOf("{{") === -1 && TEMPLATE_PATH !== "") {
        var templateFile = new File(TEMPLATE_PATH);
        if (templateFile.exists) {
            app.open(templateFile);
            $.writeln("Opened template: " + TEMPLATE_PATH);
        } else {
            alert("Template file not found:\n" + TEMPLATE_PATH);
            writeErrorLog("Template file not found: " + TEMPLATE_PATH);
            return;
        }
    }
    
    // Keep AE open after script runs (unless auto-render)
    if (AUTO_RENDER !== "true") {
        app.exitAfterLaunchAndEval = false;
    }
    
    app.beginUndoGroup("Batch Music Video Build");

    clearAllJobComps();

    // Clear render queue before adding new jobs
    for (var i = app.project.renderQueue.numItems; i >= 1; i--) {
        try { app.project.renderQueue.item(i).remove(); } catch (e) {}
    }
    $.writeln("Render queue cleared.");

    // Use injected path or fallback to prompt
    var jobsFolder;
    if (JOBS_PATH.indexOf("{{") === -1 && JOBS_PATH !== "") {
        jobsFolder = new Folder(JOBS_PATH);
    } else {
        jobsFolder = Folder.selectDialog("Select your /jobs folder");
    }
    if (!jobsFolder || !jobsFolder.exists) {
        alert("Jobs folder not found: " + (JOBS_PATH || "not specified"));
        return;
    }

    var subfolders = jobsFolder.getFiles(function (f) { return f instanceof Folder; });
    var jsonFiles = [];
    
    for (var i = 0; i < subfolders.length; i++) {
        // Only look for job_data.json in each job folder
        var files = subfolders[i].getFiles("job_data.json");
        if (files && files.length > 0) {
            jsonFiles.push(files[0]);
        }
    }
    
    if (jsonFiles.length === 0) {
        alert("No job_data.json files found inside subfolders of " + jobsFolder.fsName);
        return;
    }

    for (var j = 0; j < jsonFiles.length; j++) {
        var jobFile = jsonFiles[j];
        if (!jobFile.exists || !jobFile.open("r")) continue;
        var jsonText = jobFile.read();
        jobFile.close();
        if (!jsonText) continue;

        var jobData;
        try { jobData = JSON.parse(jsonText); }
        catch (e) { alert("Error parsing " + jobFile.name + ": " + e.toString()); continue; }

        // Get job folder from the json file location (reliable)
        var jobFolder = jobFile.parent;
        
        // Convert paths to absolute WITH FALLBACKS (like Nova)
        jobData.audio_trimmed = toAbsolute(jobData.audio_trimmed) || (jobFolder.fsName + "/audio_trimmed.wav");
        jobData.cover_image   = toAbsolute(jobData.cover_image) || (jobFolder.fsName + "/cover.jpg");
        jobData.lyrics_file   = toAbsolute(jobData.lyrics_file) || (jobFolder.fsName + "/lyrics.json");
        jobData.job_folder    = jobFolder.fsName.replace(/\\/g, "/");

        $.writeln("──────── Job " + jobData.job_id + " ────────");

        var audioFile = new File(jobData.audio_trimmed);
        var imageFile = new File(jobData.cover_image);
        if (!audioFile.exists) { alert(" Missing audio:\n" + jobData.audio_trimmed); continue; }
        if (!imageFile.exists) { alert(" Missing image:\n" + jobData.cover_image); continue; }

        // Duplicate MAIN
        var template = findCompByName("MAIN");
        var newComp = template.duplicate();
        newComp.name = "MV_JOB_" + ("00" + jobData.job_id).slice(-3);

        // Move duplicated comp into correct OUTPUT folder
        moveItemToFolder(newComp, "OUTPUT" + jobData.job_id);

        // Relink existing imported assets instead of replacing
        relinkFootageInsideOutputFolder(jobData.job_id, jobData.audio_trimmed, jobData.cover_image);

        autoResizeCoverInOutput(jobData.job_id);
        setWorkAreaToAudioDuration(jobData.job_id);
        setOutputWorkAreaToAudio(jobData.job_id, jobData.audio_trimmed);
        updateSongTitle(jobData.job_id, jobData.song_title);


        applyBackgroundColors(jobData.job_id, jobData.colors);
        applyComplementarySpectrumColor(jobData.job_id, jobData.colors[0]);


        // Beat Sync Spotlight
        try {
            applyBeatSync(jobData.job_id, jobData.beats);
            $.writeln(" Applied beat sync for job " + jobData.job_id);
        } catch (e) {
            $.writeln(" Beat sync failed for job " + jobData.job_id + ": " + e.toString());
        }

        // Lyrics
        var outputComp, lyricComp;
        try { outputComp = findCompByName("OUTPUT " + jobData.job_id); }
        catch (e) { $.writeln(" Missing OUTPUT " + jobData.job_id + " — skipping job."); continue; }
        try { lyricComp = findCompByName("LYRIC FONT " + jobData.job_id); }
        catch (e) { $.writeln(" Missing LYRIC FONT " + jobData.job_id + " — skipping job."); continue; }

        var parsed = parseLyricsFile(jobData.lyrics_file);
        pushLyricsToCarousel(lyricComp, parsed.linesArray);
        setAudioMarkersFromTArray(lyricComp, parsed.tAndText);

        // Album art
        try {
            var assetsComp = findCompByName("Assets " + jobData.job_id);
            retargetImageLayersToFootage(assetsComp, "COVER");
            $.writeln(" Album art retargeted to COVER for job " + jobData.job_id);
        } catch (e) {
            $.writeln(" Assets " + jobData.job_id + " not found — skipping album art.");
        }


        // Add to render queue
        try {
            var renderPath = addToRenderQueue(
                outputComp,
                jobData.job_folder,
                jobData.job_id,
                jobData.song_title
            );

            $.writeln(" Queued: " + renderPath);
        } catch (e) {
            $.writeln(" Render queue error: " + e);
        }
    }

    app.endUndoGroup();
    
    // Auto-render if flag is set
    if (AUTO_RENDER === "true") {
        if (app.project.renderQueue.numItems > 0) {
            $.writeln("AUTO_RENDER: Starting render...");
            app.project.renderQueue.render();
            $.writeln("AUTO_RENDER: Render complete.");
        } else {
            $.writeln("AUTO_RENDER: No items in render queue.");
            writeErrorLog("No items in render queue");
        }
        app.quit();
    } else {
        alert(" All jobs queued. Review in Render Queue, then click Render.");
    }
}

// Write error log for batch processing
function writeErrorLog(message) {
    if (JOBS_PATH.indexOf("{{") === -1 && JOBS_PATH !== "") {
        var errorFile = new File(JOBS_PATH + "/batch_error.txt");
        errorFile.open("w");
        errorFile.write(message);
        errorFile.close();
    }
}


// -----------------------------
// Helper Functions
// -----------------------------

function findFolderByName(name) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FolderItem && it.name === name) return it;
    }
    return null;
}

function moveItemToFolder(item, folderName) {
    var folder = findFolderByName(folderName);
    if (folder) item.parentFolder = folder;
}

function toAbsolute(p) {
    if (!p) return p;
    p = p.replace(/\\/g, "/");

    // First, try as-is (absolute path)
    var f = new File(p);
    if (f.exists) {
        return f.fsName.replace(/\\/g, "/");
    }

    // Fallback: treat as relative to project root
    // scripts/JSX/your.jsx  → parent = JSX → parent = scripts → parent = project root
    var base = File($.fileName).parent.parent.parent;
    f = new File(base.fsName + "/" + p);

    return f.fsName.replace(/\\/g, "/");
}

function hexToRGB(hex) {
    if (!hex || typeof hex !== "string") return [1, 1, 1];
    hex = hex.replace("#", "");
    try {
        return [
            parseInt(hex.substring(0, 2), 16) / 255,
            parseInt(hex.substring(2, 4), 16) / 255,
            parseInt(hex.substring(4, 6), 16) / 255
        ];
    } catch (e) { return [1, 1, 1]; }
}

function findCompByName(name) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof CompItem && it.name === name) return it;
    }
    throw new Error("Comp not found: " + name);
}

function readTextFile(p) {
    var f = new File(p);
    f.open("r");
    var t = f.read();
    f.close();
    return t;
}

function parseLyricsFile(p) {
    var raw = readTextFile(p);
    if (!raw || raw.replace(/^\s+|\s+$/g, "").length === 0) {
        $.writeln(" parseLyricsFile: empty file at " + p);
        return { linesArray: [], tAndText: [] };
    }

    // Strip UTF-8 BOM if present
    raw = raw.replace(/^\uFEFF/, "");

    var data;
    try { data = JSON.parse(raw); }
    catch (e) {
        $.writeln(" parseLyricsFile: JSON parse error — " + e.toString());
        return { linesArray: [], tAndText: [] };
    }

    var linesArray = [], tAndText = [];

    for (var i = 0; i < data.length; i++) {
        var cur = String(data[i].lyric_current || data[i].cur || "");
        var t   = Number(data[i].t || 0);

        // Normalise line endings: \r\n → \r, bare \n → \r
        // AE text layers use \r as the line-break character inside expressions.
        cur = cur.replace(/\r\n/g, "\r").replace(/\n/g, "\r");

        // Apply word-wrap if Python did not already insert a line break.
        // wrapTwoLines() is a no-op when cur is short enough.
        if (cur.indexOf("\r") === -1) {
            cur = wrapTwoLines(cur, MAX_CHARS_PER_LINE);
        }

        linesArray.push(cur);
        tAndText.push({ t: t, cur: cur });
    }
    return { linesArray: linesArray, tAndText: tAndText };
}


function wrapTwoLines(s, limit) {
    s = String(s);

    // DO NOT wrap if Python already inserted \r
    if (s.indexOf("\r") !== -1) {
        return s;
    }

    if (s.length <= limit) return s;

    var cut = s.lastIndexOf(" ", limit);
    if (cut < 0) cut = limit;

    return s.substring(0, cut) + "\r" + s.substring(cut + 1).replace(/^\s+/, "");
}




function escapeLyricForExpression(l) {
    if (!l) return "";

    // 1. Escape backslashes FIRST
    l = l.replace(/\\/g, "\\\\");    

    // 2. Escape quotes
    l = l.replace(/"/g, '\\"');      

    // 3. Convert actual carriage-return characters to the literal sequence "\r"
    l = l.replace(/\r/g, "\\r");

    return l;
}

function replaceLyricArrayInLayer(layer, linesArray) {
    var lines = [];

    for (var i = 0; i < linesArray.length; i++) {
        var raw = String(linesArray[i] || "");
        var esc = escapeLyricForExpression(raw);
        lines.push('"' + esc + '"');
    }

    var newBlock =
        "var lyrics = [\n    " +
        lines.join(",\n    ") +
        "\n];";

    var prop = layer.property("Source Text");
    if (!prop) return;

    var expr = prop.expression || "";
    var re = /var\s+lyrics\s*=\s*\[[\s\S]*?\];/i;

    if (re.test(expr)) {
        prop.expression = expr.replace(re, newBlock);
    } else {
        prop.expression = newBlock + "\n" + expr;
    }
}





function pushLyricsToCarousel(comp, arr) {
    var names = ["LYRIC PREVIOUS", "LYRIC CURRENT", "LYRIC NEXT 1", "LYRIC NEXT 2"];
    for (var i = 0; i < names.length; i++) {
        var lyr = comp.layer(names[i]);
        if (lyr) replaceLyricArrayInLayer(lyr, arr);
    }
}

function clearAllMarkers(layer) {
    var mk = layer.property("Marker");
    if (!mk) return;
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);
}

function ensureAudioLayer(comp) {
    var lyr = comp.layer("AUDIO");
    if (lyr) return lyr;

    // Fallback: find the first AVLayer that has audio enabled
    for (var i = 1; i <= comp.numLayers; i++) {
        var L = comp.layer(i);
        if (L instanceof AVLayer && L.hasAudio) {
            // rename it so expressions looking for "AUDIO" keep working
            try { L.name = "AUDIO"; } catch (_) {}
            return L;
        }
    }
    return null;
}

function setAudioMarkersFromTArray(lyricComp, tAndText) {
    var audio = ensureAudioLayer(lyricComp);
    if (!audio) { $.writeln(" No AUDIO layer found in " + lyricComp.name); return; }

    var mk = audio.property("Marker");
    if (!mk) { $.writeln(" No Marker prop on AUDIO in " + lyricComp.name); return; }

    // Clear markers
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);

    var lastT = 0;
    for (var k = 0; k < tAndText.length; k++) {
        var t = Number(tAndText[k].t) || 0;
        var name = String(tAndText[k].cur || ("LYRIC_" + (k + 1)));
        try {
            mk.setValueAtTime(t, new MarkerValue(name));
            if (t > lastT) lastT = t;
        } catch (e) {
            $.writeln(" Marker set failed at " + t + "s: " + e.toString());
        }
    }
    if (lastT + 2 > lyricComp.duration) lyricComp.duration = lastT + 2;
}


function addToRenderQueue(comp, jobFolder, jobId, songTitle) {
    try {
        // Normalize path
        jobFolder = String(jobFolder).replace(/\\/g, "/");
        
        var root = new Folder(jobFolder).parent;
        var renderDir = new Folder(root.fsName + "/renders");
        if (!renderDir.exists) renderDir.create();

        var safeTitle = sanitizeFilename(songTitle);
        var filename = safeTitle + ".mp4";
        var outPath = renderDir.fsName.replace(/\\/g, "/") + "/" + filename;
        var outFile = new File(outPath);

        var rq = app.project.renderQueue.items.add(comp);
        try { rq.applyTemplate("Best Settings"); } catch (e) {}
        try { rq.outputModule(1).applyTemplate("H.264"); } catch (e) {}
        rq.outputModule(1).file = outFile;

        return outPath;
    } catch (err) {
        $.writeln("addToRenderQueue error: " + err.toString());
        return null;
    }
}



function replaceInAllComps(compName, layerName, newItem) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof CompItem && it.name.indexOf(compName) !== -1) {
            for (var j = 1; j <= it.numLayers; j++) {
                var lyr = it.layer(j);
                if (lyr.name === layerName && lyr.source) {
                    lyr.replaceSource(newItem, false);
                }
            }
        }
    }
}
// Relink a Project FootageItem by its *project-panel name* (keeps name & all uses)
function relinkFootageByName(itemName, newFilePath) {
    var newFile = new File(newFilePath);
    if (!newFile.exists) {
        $.writeln(" File not found: " + newFilePath);
        return;
    }
    var found = false;
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FootageItem && it.name.toUpperCase() === itemName.toUpperCase()) {
            try {
                it.replace(newFile);     // relink only, name stays the same
                found = true;
                $.writeln(" Relinked '" + it.name + "' to " + newFile.fsName);
            } catch (e) {
                $.writeln(" Could not relink '" + it.name + "': " + e.toString());
            }
        }
    }
    if (!found) $.writeln(" Footage named '" + itemName + "' not found in Project.");
}

// Auto-resize any COVER layer to fit comp safely (preserves aspect)
function autoResizeCoverInOutput(jobId) {
    var comp;
    try { comp = findCompByName("OUTPUT " + jobId); }
    catch(_) { return; }
    if (!comp) return;

    var cw = comp.width;
    var ch = comp.height;

    // Find COVER layer
    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (!(lyr instanceof AVLayer)) continue;

        var isCover = (lyr.name.toUpperCase() === "COVER") ||
                      (lyr.source && lyr.source.name.toUpperCase() === "COVER");
        if (!isCover) continue;

        var lw = lyr.source.width;
        var lh = lyr.source.height;

        if (!lw || !lh) continue;

        // --- FILL SCALE (no black bars, image always fills the comp) ---
        var scaleW = cw / lw;
        var scaleH = ch / lh;

        // Choose the LARGER scale so the image covers fully
        var scale = 100 * Math.max(scaleW, scaleH);

        try {
            lyr.property("Scale").setValue([scale, scale]);
            // Optional: center the layer
            lyr.property("Position").setValue([cw / 2, ch / 2]);
        } catch(e) {}

        $.writeln(" Auto-Fill scaled COVER in " + comp.name + " (scale: " + scale + ")");
        return;
    }

    $.writeln(" COVER layer not found in OUTPUT " + jobId);
}


function retargetImageLayersToFootage(assetComp, footageName) {
    if (!assetComp) return;

    var coverFootage = null;
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FootageItem && it.name.toUpperCase() === footageName.toUpperCase()) {
            coverFootage = it;
            break;
        }
    }

    if (!coverFootage) {
        $.writeln(" Footage '" + footageName + "' not found.");
        return;
    }

    for (var L = 1; L <= assetComp.numLayers; L++) {
        var lyr = assetComp.layer(L);
        if (!(lyr instanceof AVLayer)) continue;
        if (!(lyr.source instanceof FootageItem)) continue;

        var srcName = (lyr.source.name || "").toLowerCase();
        var lyrName = (lyr.name || "").toLowerCase();

        // only target layers clearly meant to be the album art
        var isCoverLayer =
            lyrName === "cover" ||
            lyrName.indexOf("album") !== -1 ||
            lyrName.indexOf("art") !== -1 ||
            srcName === "cover" ||
            srcName.indexOf("album") !== -1;

        if (!isCoverLayer) continue;

        try {
            lyr.replaceSource(coverFootage, false); // keep transform, effects, etc.
            $.writeln(" Replaced album art layer '" + lyr.name + "' with COVER footage in " + assetComp.name);
        } catch (e) {
            $.writeln(" Could not replace '" + lyr.name + "': " + e.toString());
        }
    }
}

// Set comp work area to audio duration
function setWorkAreaToAudioDuration(jobId) {
    var comp = findCompByName("LYRIC FONT " + jobId);
    if (!comp) return;

    var audio = ensureAudioLayer(comp);
    if (!audio || !audio.source || !audio.source.duration) return;

    var dur = audio.source.duration;
    
    comp.duration = dur;
    comp.workAreaStart = 0;
    comp.workAreaDuration = dur;
    
}



// Update title text inside Assets comp
// Update the TOPMOST text layer inside "Assets N" to the provided title
function updateSongTitle(jobId, titleText) {
    if (!titleText) return;
    try {
        var assetsComp = findCompByName("Assets " + jobId);
        if (!assetsComp) { $.writeln(" Assets " + jobId + " not found."); return; }

        // Find the first layer that has a Source Text property (topmost text layer)
        var targetTextLayer = null;
        for (var i = 1; i <= assetsComp.numLayers; i++) {
            var lyr = assetsComp.layer(i);
            var txtProp = lyr.property("Source Text");
            if (txtProp) { targetTextLayer = lyr; break; }
        }

        if (!targetTextLayer) {
            $.writeln(" No text layer found in " + assetsComp.name);
            return;
        }

        var txtProp = targetTextLayer.property("Source Text");
        var doc = txtProp.value;       // TextDocument
        doc.text = String(titleText); 
        txtProp.setValue(doc);

        $.writeln(" Set song title on layer '" + targetTextLayer.name +
                  "' in " + assetsComp.name + " to: " + titleText);
    } catch (e) {
        $.writeln(" Could not update title for job " + jobId + ": " + e.toString());
    }
}

function relinkFootageInsideOutputFolder(jobId, audioPath, coverPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln(" OUTPUT" + jobId + " folder not found.");
        return;
    }

    // Find the nested "Assets OTX" folder inside
    var assetsFolder = null;
    for (var i = 1; i <= outputFolder.numItems; i++) {
        var it = outputFolder.item(i);
        if (it instanceof FolderItem && it.name.toUpperCase().indexOf("ASSETS OT") === 0) {
            assetsFolder = it;
            break;
        }
    }

    if (!assetsFolder) {
        $.writeln(" Assets folder not found inside OUTPUT" + jobId);
        return;
    }

    var audioFile = new File(audioPath);
    var coverFile = new File(coverPath);
    if (!audioFile.exists) {
        $.writeln(" Missing audio file for job " + jobId);
        return;
    }
    if (!coverFile.exists) {
        $.writeln(" Missing cover file for job " + jobId);
        return;
    }

    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (!(it instanceof FootageItem)) continue;

        var name = (it.name || "").toUpperCase();
        
        // Match audio files - check for AUDIO, audio_trimmed.wav, or any .wav file
        var isAudio = (name === "AUDIO") || 
                      (name.indexOf("AUDIO") === 0) || 
                      (name.indexOf(".WAV") !== -1);
        
        try {
            if (isAudio) {
                it.replace(audioFile);
                $.writeln(" Replaced " + it.name + " inside Assets OT" + jobId);
            } else if (name === "COVER") {
                it.replace(coverFile);
                $.writeln(" Replaced COVER inside Assets OT" + jobId);
            }
        } catch (e) {
            $.writeln(" Could not relink " + it.name + ": " + e.toString());
        }
    }
}

function setOutputWorkAreaToAudio(jobId, audioPath) {
    // Get duration from the already-relinked audio layer in LYRIC FONT comp.
    // This avoids importing and immediately removing the audio file for every job,
    // which was happening 12× per batch and served no purpose.
    var dur = 0;
    try {
        var lfc   = findCompByName("LYRIC FONT " + jobId);
        var audio = ensureAudioLayer(lfc);
        if (audio && audio.source && audio.source.duration) {
            dur = audio.source.duration;
        }
    } catch (_) {}

    // Fallback: import the file if the layer route failed
    if (!dur) {
        try {
            var af = new File(audioPath);
            if (af.exists) {
                var tmp = app.project.importFile(new ImportOptions(af));
                dur = tmp.duration;
                tmp.remove();
                $.writeln(" setOutputWorkAreaToAudio: used import fallback for job " + jobId);
            }
        } catch (e) {
            $.writeln(" setOutputWorkAreaToAudio: could not determine duration for job " + jobId + ": " + e.toString());
            return;
        }
    }

    if (!dur) { $.writeln(" setOutputWorkAreaToAudio: zero duration for job " + jobId); return; }

    try {
        var comp = findCompByName("OUTPUT " + jobId);
        comp.duration = dur;
        comp.workAreaStart = 0;
        comp.workAreaDuration = dur;
    } catch (e) {
        $.writeln(" Could not set OUTPUT " + jobId + " duration: " + e.toString());
    }
}




function applyBeatSync(jobId, beatsArray) {
    if (!beatsArray || beatsArray.length < 2) {
        $.writeln(" Not enough beats for job " + jobId);
        return;
    }

    var comp = findCompByName("OUTPUT " + jobId);
    if (!comp) {
        $.writeln(" OUTPUT " + jobId + " not found");
        return;
    }

    var layer = comp.layer("Spot Light 2");
    if (!layer) {
        $.writeln(" Spot Light 2 not found in OUTPUT " + jobId);
        return;
    }


    var intensity =
        layer.property("ADBE Light Options Group") &&
        layer.property("ADBE Light Options Group").property("ADBE Light Intensity");

    if (!intensity)
        intensity = layer.property("Light Options") &&
                    layer.property("Light Options").property("Intensity");

    if (!intensity && layer.property("Light Options"))
        intensity = layer.property("Light Options").property(2);

    if (!intensity) {
        $.writeln(" Intensity property not found");
        return;
    }

 
    for (var k = intensity.numKeys; k >= 1; k--) intensity.removeKey(k);

    var PEAK     = 75;   // spotlight intensity on the beat hit
    var BASE     = 15;   // resting intensity between beats
    var DECAY    = 0.08; // seconds to hold peak before fading (avoids jumpy single-frame flash)

    var oneFrame = 1 / comp.frameRate;

    for (var i = 0; i < beatsArray.length - 1; i++) {
        var t     = beatsArray[i];
        var nextT = beatsArray[i + 1];

        // 1. Instant jump to PEAK on the beat (HOLD so the hit is immediate, not eased in)
        intensity.setValueAtTime(t, PEAK);
        var kPeak = intensity.nearestKeyIndex(t);
        intensity.setInterpolationTypeAtKey(kPeak, KeyframeInterpolationType.HOLD);

        // 2. Hold the peak for DECAY seconds, then begin linear fall to BASE
        var tDecay = Math.min(t + DECAY, nextT - oneFrame);
        if (tDecay > t) {
            intensity.setValueAtTime(tDecay, PEAK);
            var kDecay = intensity.nearestKeyIndex(tDecay);
            intensity.setInterpolationTypeAtKey(kDecay, KeyframeInterpolationType.LINEAR);
        }

        // 3. Reach BASE one frame before the next beat so the next hit always punches from low
        var tBase = nextT - oneFrame;
        if (tBase > tDecay) {
            intensity.setValueAtTime(tBase, BASE);
            var kBase = intensity.nearestKeyIndex(tBase);
            intensity.setInterpolationTypeAtKey(kBase, KeyframeInterpolationType.LINEAR);
        }
    }

    // Final beat — HOLD peak, no fade (song ends)
    var lastBeat = beatsArray[beatsArray.length - 1];
    intensity.setValueAtTime(lastBeat, PEAK);
    var kFinal = intensity.nearestKeyIndex(lastBeat);
    intensity.setInterpolationTypeAtKey(kFinal, KeyframeInterpolationType.HOLD);

    $.writeln(" Beat sync applied: HOLD peak (" + DECAY + "s) → linear decay to " + BASE + " per beat.");
}

function applyComplementarySpectrumColor(jobId, baseHexColor) {
    try {
        var comp = findCompByName("Assets " + jobId);
        if (!comp) {
            $.writeln("Assets " + jobId + " not found.");
            return;
        }

        // Find the 'Black Solid 1' layer
        var target = null;
        for (var i = 1; i <= comp.numLayers; i++) {
            if (comp.layer(i).name === "Black Solid 1") {
                target = comp.layer(i);
                break;
            }
        }

        if (!target) {
            $.writeln("Black Solid 1 not found in Assets " + jobId);
            return;
        }

        // Find the Audio Spectrum effect
        var fx = target.property("ADBE Effect Parade").property("Audio Spectrum");
        if (!fx) {
            $.writeln("Audio Spectrum effect missing on Black Solid 1 for job " + jobId);
            return;
        }

        // Convert hex → RGB (normalized)
        function hexToRGBnorm(hex) {
            hex = hex.replace("#", "");
            return [
                parseInt(hex.substr(0, 2), 16) / 255,
                parseInt(hex.substr(2, 2), 16) / 255,
                parseInt(hex.substr(4, 2), 16) / 255
            ];
        }

        // Compute complementary color
        function complementaryHex(hex) {
            hex = hex.replace("#", "");
            var r = 255 - parseInt(hex.substr(0, 2), 16);
            var g = 255 - parseInt(hex.substr(2, 2), 16);
            var b = 255 - parseInt(hex.substr(4, 2), 16);
            return [r / 255, g / 255, b / 255];  // AE normalized RGB
        }

        var compColor = complementaryHex(baseHexColor);

        // Apply to Inside Color (+1)
        var inside = fx.property("Inside Color");
        if (inside) inside.setValue(compColor);

        // Apply to Outside Color (+2)
        var outside = fx.property("Outside Color");
        if (outside) outside.setValue(compColor);

        $.writeln("Applied complementary Audio Spectrum color to Assets " + jobId);

    } catch (err) {
        $.writeln("Error applying complementary spectrum color for job " 
                   + jobId + ": " + err.toString());
    }
}
function setSolidLayerColor(layer, hex) {
    if (!layer || !layer.source || !layer.source.mainSource) return;

    try {
        layer.source.mainSource.color = hexToRGB(hex);
    } catch (e) {
        $.writeln(" Failed to recolor layer " + layer.name + ": " + e.toString());
    }
}

function applyBackgroundColors(jobId, colors) {
    if (!colors || colors.length < 2) {
        $.writeln(" Not enough colors for job " + jobId);
        return;
    }

    var bgComp;
    try {
        bgComp = findCompByName("BACKGROUND " + jobId);
    } catch (_) {
        $.writeln(" BACKGROUND " + jobId + " not found");
        return;
    }

    // Find the Gradient layer
    var gradientLayer = bgComp.layer("Gradient");
    if (!gradientLayer) {
        $.writeln(" Gradient layer not found in BACKGROUND " + jobId);
        return;
    }

    // Find the 4-Color Gradient effect
    var effectParade = gradientLayer.property("ADBE Effect Parade");
    if (!effectParade) {
        $.writeln(" No effects on Gradient layer in BACKGROUND " + jobId);
        return;
    }

    var gradient4Color = effectParade.property("4-Color Gradient");
    if (!gradient4Color) {
        $.writeln(" 4-Color Gradient effect not found on Gradient layer in BACKGROUND " + jobId);
        return;
    }

    // Apply colors (Color 1, Color 2, Color 3, Color 4)
    // Python gives us 2 colors, so: Color1=colors[0], Color2=colors[1], Color3=colors[0], Color4=colors[0]
    try {
        var color1Prop = gradient4Color.property("Color 1");
        var color2Prop = gradient4Color.property("Color 2");
        var color3Prop = gradient4Color.property("Color 3");
        var color4Prop = gradient4Color.property("Color 4");

        if (color1Prop) color1Prop.setValue(hexToRGB(colors[0]));
        if (color2Prop) color2Prop.setValue(hexToRGB(colors[1]));
        if (color3Prop) color3Prop.setValue(hexToRGB(colors.length > 2 ? colors[2] : colors[0]));
        if (color4Prop) color4Prop.setValue(hexToRGB(colors[0])); // Repeat dominant color

        $.writeln(" 4-Color Gradient updated for job " + jobId);
    } catch (e) {
        $.writeln(" Failed to apply gradient colors for job " + jobId + ": " + e.toString());
    }
}


function sanitizeFilename(name) {
    if (!name) return "untitled";

    return String(name)
        .replace(/[\/\\:*?"<>|]/g, "")   // illegal chars
        .replace(/\s+/g, " ")            // collapse spaces
        .replace(/^\s+|\s+$/g, "");      // trim
}
function clearAllJobComps() {
    $.writeln(" Clearing all MV_JOB comps...");
    var count = 0;
    
    for (var i = app.project.numItems; i >= 1; i--) {
        var it = app.project.item(i);
        
        if (it instanceof CompItem && it.name.indexOf("MV_JOB_") === 0) {
            try {
                it.remove();
                count++;
            } catch (e) {}
        }
    }
    
    $.writeln(" ✓ Deleted " + count + " old job comps");
}
// -----------------------------
main();