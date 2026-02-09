// -------------------------------------------------------
// VISUALS NOVA - After Effects Automation
// Modified Aurora template with word-by-word reveal
// -------------------------------------------------------
// Usage:
//  1) Run main_nova.py to build /jobs/job_001 → job_012
//  2) Open AE project (same Aurora template)
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
            if (t === "string") obj = '"' + obj.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
            return String(obj);
        } else {
            var n, v, json = [], arr = (obj && obj.constructor === Array);
            for (n in obj) {
                v = obj[n];
                t = typeof v;
                if (t === "string") v = '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
                else if (t === "object" && v !== null) v = JSON.stringify(v);
                json.push((arr ? "" : '"' + n + '":') + String(v));
            }
            return (arr ? "[" : "{") + String(json) + (arr ? "]" : "}");
        }
    };
}


// -----------------------------
// MAIN
// -----------------------------
function main() {
    app.beginUndoGroup("NOVA Batch Music Video Build");

    clearAllJobComps();

    var jobsFolder = Folder.selectDialog("Select your /jobs folder (Visuals-Nova/jobs)");
    if (!jobsFolder) return;

    var subfolders = jobsFolder.getFiles(function (f) { return f instanceof Folder; });
    var jsonFiles = [];
    
    for (var i = 0; i < subfolders.length; i++) {
        // Look for nova_data.json in each job folder
        var files = subfolders[i].getFiles("nova_data.json");
        if (files && files.length > 0) {
            jsonFiles.push(files[0]);
        }
    }
    
    if (jsonFiles.length === 0) {
        alert("No nova_data.json files found inside subfolders of " + jobsFolder.fsName);
        return;
    }

    for (var j = 0; j < jsonFiles.length; j++) {
        var novaFile = jsonFiles[j];
        if (!novaFile.exists || !novaFile.open("r")) continue;
        var novaText = novaFile.read();
        novaFile.close();
        if (!novaText) continue;

        var novaData;
        try { novaData = JSON.parse(novaText); }
        catch (e) { alert("Error parsing " + novaFile.name + ": " + e.toString()); continue; }

        // Also read job_data.json for paths and metadata
        var jobFolder = novaFile.parent;
        var jobDataFile = new File(jobFolder.fsName + "/job_data.json");
        var jobData = {};
        
        if (jobDataFile.exists && jobDataFile.open("r")) {
            var jobDataText = jobDataFile.read();
            jobDataFile.close();
            try { jobData = JSON.parse(jobDataText); }
            catch (e) { $.writeln("Could not parse job_data.json"); }
        }

        // FIXED: Use job folder path directly instead of toAbsolute
        // The audio file is always in the job folder
        var audioPath = jobFolder.fsName + "/audio_trimmed.wav";
        jobData.audio_trimmed = audioPath.replace(/\\/g, "/");
        jobData.job_folder = jobFolder.fsName.replace(/\\/g, "/");
        
        // For Nova, we may or may not have cover image (optional)
        var hasCoverImage = false;
        if (jobData.cover_image) {
            // Check if cover exists in job folder
            var coverPath = jobFolder.fsName + "/cover.png";
            var imageFile = new File(coverPath);
            if (imageFile.exists) {
                jobData.cover_image = coverPath.replace(/\\/g, "/");
                hasCoverImage = true;
            }
        }

        var jobId = jobData.job_id || (j + 1);
        var songTitle = jobData.song_title || "Unknown";
        var markers = novaData.markers || [];

        $.writeln("──────── NOVA Job " + jobId + " ────────");
        $.writeln("Song: " + songTitle);
        $.writeln("Markers: " + markers.length);
        $.writeln("Audio path: " + jobData.audio_trimmed);

        var audioFile = new File(jobData.audio_trimmed);
        if (!audioFile.exists) { 
            alert("Missing audio:\n" + jobData.audio_trimmed); 
            continue; 
        }

        // Duplicate MAIN template
        var template = findCompByName("MAIN");
        var newComp = template.duplicate();
        newComp.name = "NOVA_JOB_" + ("00" + jobId).slice(-3);

        // Move duplicated comp into correct OUTPUT folder
        moveItemToFolder(newComp, "OUTPUT" + jobId);

        // Relink audio (and cover if exists)
        if (hasCoverImage) {
            relinkFootageInsideOutputFolder(jobId, jobData.audio_trimmed, jobData.cover_image);
            autoResizeCoverInOutput(jobId);
        } else {
            relinkAudioOnly(jobId, jobData.audio_trimmed);
        }
        
        setWorkAreaToAudioDuration(jobId);
        setOutputWorkAreaToAudio(jobId, jobData.audio_trimmed);
        updateSongTitle(jobId, songTitle);

        // Lyrics - NOVA STYLE (word-by-word)
        var lyricComp;
        try { lyricComp = findCompByName("LYRIC FONT " + jobId); }
        catch (e) { $.writeln("Missing LYRIC FONT " + jobId + " – skipping lyrics."); continue; }

        // Add markers to AUDIO layer in LYRIC FONT comp
        addNovaMarkersToAudio(lyricComp, markers);
        
        // Inject word-by-word segments into LYRIC_TEXT expression
        injectNovaSegmentsToLyricText(lyricComp, markers);

        // Add markers to BACKGROUND comp for color flip
        try {
            var bgComp = findCompByName("BACKGROUND " + jobId);
            addNovaMarkersToBackground(bgComp, markers);
            $.writeln("Added markers to BACKGROUND " + jobId);
        } catch (e) {
            $.writeln("BACKGROUND " + jobId + " not found – skipping color flip markers.");
        }

        // Album art (optional for Nova)
        if (hasCoverImage) {
            try {
                var assetsComp = findCompByName("Assets " + jobId);
                retargetImageLayersToFootage(assetsComp, "COVER");
                $.writeln("Album art retargeted for job " + jobId);
            } catch (e) {
                $.writeln("Assets " + jobId + " not found – skipping album art.");
            }
        }

        // Add to render queue
        try {
            var outputComp = null;
            // Try different naming conventions
            try { outputComp = findCompByName("OUTPUT " + jobId); } catch(e1) {}
            if (!outputComp) {
                try { outputComp = findCompByName("OUTPUT" + jobId); } catch(e2) {}
            }
            if (!outputComp) {
                try { outputComp = findCompByName("OUTPUT " + jobId + " "); } catch(e3) {}
            }
            
            if (outputComp) {
                var renderPath = addToRenderQueue(
                    outputComp,
                    jobData.job_folder,
                    jobId,
                    songTitle,
                    "_NOVA"
                );
                $.writeln("Queued: " + renderPath);
            } else {
                $.writeln("Could not find OUTPUT comp for job " + jobId + " - skipping render queue");
            }
        } catch (e) {
            $.writeln("Render queue error: " + e);
        }
    }

    alert("NOVA batch processing complete!\n\nReview in Render Queue, then click Render.");
    app.endUndoGroup();
}


// -----------------------------
// NOVA-SPECIFIC FUNCTIONS
// -----------------------------

function addNovaMarkersToAudio(lyricComp, markers) {
    // Add simple markers to AUDIO layer (just for timing triggers)
    // LYRIC CONTROL reads these to determine current segment index
    
    var audio = ensureAudioLayer(lyricComp);
    if (!audio) { 
        $.writeln("No AUDIO layer found in " + lyricComp.name); 
        return; 
    }

    var mk = audio.property("Marker");
    if (!mk) { 
        $.writeln("No Marker prop on AUDIO in " + lyricComp.name); 
        return; 
    }

    // Clear existing markers
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);

    var lastT = 0;
    for (var k = 0; k < markers.length; k++) {
        var m = markers[k];
        var t = Number(m.time) || 0;
        
        // Simple marker - just the segment text as comment (like Aurora)
        var markerText = m.text || ("Segment " + (k + 1));
        
        try {
            mk.setValueAtTime(t, new MarkerValue(markerText));
            if (t > lastT) lastT = t;
        } catch (e) {
            $.writeln("Marker set failed at " + t + "s: " + e.toString());
        }
    }
    
    // Extend comp if needed
    if (lastT + 2 > lyricComp.duration) {
        lyricComp.duration = lastT + 2;
    }
    
    $.writeln("Added " + markers.length + " markers to AUDIO in " + lyricComp.name);
}


function addNovaMarkersToBackground(bgComp, markers) {
    // Add markers to the audio layer in BACKGROUND comp for color flip expression
    
    if (!bgComp) {
        $.writeln("BACKGROUND comp not provided");
        return;
    }
    
    // Find audio layer in BACKGROUND comp
    var audio = null;
    
    // Try different names
    try { audio = bgComp.layer("audio_trimmed.wav"); } catch(e) {}
    if (!audio) {
        try { audio = bgComp.layer("AUDIO"); } catch(e) {}
    }
    if (!audio) {
        // Find any audio layer
        for (var i = 1; i <= bgComp.numLayers; i++) {
            var lyr = bgComp.layer(i);
            if (lyr instanceof AVLayer && lyr.hasAudio) {
                audio = lyr;
                break;
            }
        }
    }
    
    if (!audio) {
        $.writeln("No audio layer found in " + bgComp.name);
        return;
    }
    
    var mk = audio.property("Marker");
    if (!mk) {
        $.writeln("No Marker property on audio layer in " + bgComp.name);
        return;
    }
    
    // Clear existing markers
    for (var i = mk.numKeys; i >= 1; i--) mk.removeKey(i);
    
    // Add simple markers for each segment (just need count for color flip)
    for (var k = 0; k < markers.length; k++) {
        var m = markers[k];
        var t = Number(m.time) || 0;
        
        try {
            mk.setValueAtTime(t, new MarkerValue("Segment " + (k + 1)));
        } catch (e) {
            $.writeln("Background marker failed at " + t + "s: " + e.toString());
        }
    }
    
    $.writeln("Added " + markers.length + " markers to BACKGROUND audio for color flip");
}


function injectNovaSegmentsToLyricText(lyricComp, markers) {
    // Build segments array and inject into LYRIC_TEXT or similar text layer
    
    // Find the lyric text layer
    var lyricLayer = null;
    var possibleNames = ["LYRIC_TEXT", "LYRIC TEXT", "LYRIC CURRENT", "Lyrics", "Text"];
    
    for (var n = 0; n < possibleNames.length; n++) {
        try {
            lyricLayer = lyricComp.layer(possibleNames[n]);
            if (lyricLayer) break;
        } catch(e) {}
    }
    
    // If not found by name, find first text layer
    if (!lyricLayer) {
        for (var i = 1; i <= lyricComp.numLayers; i++) {
            var lyr = lyricComp.layer(i);
            if (lyr instanceof TextLayer) {
                lyricLayer = lyr;
                break;
            }
        }
    }
    
    if (!lyricLayer) {
        $.writeln("No text layer found in " + lyricComp.name);
        return;
    }
    
    // Build the segments array for the expression
    var segmentsCode = "var segments = [\n";
    
    for (var k = 0; k < markers.length; k++) {
        var m = markers[k];
        var text = escapeForExpression(m.text || "");
        var wordsArr = m.words || [];
        
        // Build words array
        var wordsCode = "[";
        for (var w = 0; w < wordsArr.length; w++) {
            var word = wordsArr[w];
            var wordText = escapeForExpression(word.word || "");
            var wordStart = Number(word.start) || 0;
            var wordEnd = Number(word.end) || 0;
            
            wordsCode += '{word:"' + wordText + '",start:' + wordStart.toFixed(3) + ',end:' + wordEnd.toFixed(3) + '}';
            if (w < wordsArr.length - 1) wordsCode += ",";
        }
        wordsCode += "]";
        
        segmentsCode += '    {text:"' + text + '",time:' + (Number(m.time) || 0).toFixed(3) + ',words:' + wordsCode + '}';
        if (k < markers.length - 1) segmentsCode += ",";
        segmentsCode += "\n";
    }
    
    segmentsCode += "];";
    
    // Build the full expression
    var fullExpression = segmentsCode + '\n\n' +
        '// Find current segment based on time\n' +
        'var audio = thisComp.layer("AUDIO") || thisComp.layer("audio_trimmed.wav");\n' +
        'var currentSeg = null;\n' +
        'for (var i = segments.length - 1; i >= 0; i--) {\n' +
        '    if (time >= segments[i].time) {\n' +
        '        currentSeg = segments[i];\n' +
        '        break;\n' +
        '    }\n' +
        '}\n\n' +
        '// Word-by-word reveal\n' +
        'var output = "";\n' +
        'if (currentSeg && currentSeg.words) {\n' +
        '    for (var w = 0; w < currentSeg.words.length; w++) {\n' +
        '        if (time >= currentSeg.words[w].start) {\n' +
        '            output += currentSeg.words[w].word + " ";\n' +
        '        }\n' +
        '    }\n' +
        '}\n' +
        'output.replace(/\\s+$/, "");';
    
    // Apply expression to Source Text
    var txtProp = lyricLayer.property("Source Text");
    if (txtProp) {
        txtProp.expression = fullExpression;
        $.writeln("Injected word-by-word expression into " + lyricLayer.name);
    }
}


function escapeForExpression(str) {
    if (!str) return "";
    return String(str)
        .replace(/\\/g, "\\\\")
        .replace(/"/g, '\\"')
        .replace(/\r/g, "\\r")
        .replace(/\n/g, "\\n");
}


// -----------------------------
// AUDIO/FOOTAGE FUNCTIONS
// -----------------------------

function relinkAudioOnly(jobId, audioPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln("OUTPUT" + jobId + " folder not found.");
        return;
    }

    // Find the nested "Assets OT" folder inside
    var assetsFolder = null;
    for (var i = 1; i <= outputFolder.numItems; i++) {
        var it = outputFolder.item(i);
        if (it instanceof FolderItem && it.name.toUpperCase().indexOf("ASSETS OT") === 0) {
            assetsFolder = it;
            break;
        }
    }

    if (!assetsFolder) {
        $.writeln("Assets folder not found inside OUTPUT" + jobId);
        return;
    }

    var audioFile = new File(audioPath);
    if (!audioFile.exists) {
        $.writeln("Audio file not found: " + audioPath);
        return;
    }

    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (!(it instanceof FootageItem)) continue;

        var name = (it.name || "").toUpperCase();
        
        // Match audio files
        var isAudio = (name === "AUDIO") || 
                      (name.indexOf("AUDIO") === 0) || 
                      (name.indexOf(".WAV") !== -1);
        
        if (isAudio) {
            try {
                it.replace(audioFile);
                $.writeln("Replaced " + it.name + " inside Assets OT" + jobId);
            } catch (e) {
                $.writeln("Could not relink audio: " + e.toString());
            }
        }
    }
}


function relinkFootageInsideOutputFolder(jobId, audioPath, coverPath) {
    var outputFolder = findFolderByName("OUTPUT" + jobId);
    if (!outputFolder) {
        $.writeln("OUTPUT" + jobId + " folder not found.");
        return;
    }

    // Find the nested "Assets OT" folder inside
    var assetsFolder = null;
    for (var i = 1; i <= outputFolder.numItems; i++) {
        var it = outputFolder.item(i);
        if (it instanceof FolderItem && it.name.toUpperCase().indexOf("ASSETS OT") === 0) {
            assetsFolder = it;
            break;
        }
    }

    if (!assetsFolder) {
        $.writeln("Assets folder not found inside OUTPUT" + jobId);
        return;
    }

    var audioFile = new File(audioPath);
    var coverFile = new File(coverPath);
    
    if (!audioFile.exists) {
        $.writeln("Missing audio file: " + audioPath);
    }
    if (!coverFile.exists) {
        $.writeln("Missing cover file: " + coverPath);
    }

    for (var i = 1; i <= assetsFolder.numItems; i++) {
        var it = assetsFolder.item(i);
        if (!(it instanceof FootageItem)) continue;

        var name = (it.name || "").toUpperCase();
        try {
            // Match audio
            var isAudio = (name === "AUDIO") || 
                          (name.indexOf("AUDIO") === 0) || 
                          (name.indexOf(".WAV") !== -1);
            
            if (isAudio && audioFile.exists) {
                it.replace(audioFile);
                $.writeln("Replaced AUDIO inside Assets OT" + jobId);
            } else if (name === "COVER" && coverFile.exists) {
                it.replace(coverFile);
                $.writeln("Replaced COVER inside Assets OT" + jobId);
            }
        } catch (e) {
            $.writeln("Could not relink " + it.name + ": " + e.toString());
        }
    }
}


// -----------------------------
// SHARED HELPER FUNCTIONS
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

    // Check if already absolute (starts with drive letter or /)
    if (p.match(/^[A-Za-z]:/) || p.charAt(0) === "/") {
        var f = new File(p);
        return f.fsName.replace(/\\/g, "/");
    }

    // Only prepend base for relative paths
    var f = new File(p);
    if (f.exists) {
        return f.fsName.replace(/\\/g, "/");
    }

    var base = File($.fileName).parent.parent.parent;
    f = new File(base.fsName + "/" + p);

    return f.fsName.replace(/\\/g, "/");
}

function findCompByName(name) {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof CompItem && it.name === name) return it;
    }
    throw new Error("Comp not found: " + name);
}

function ensureAudioLayer(comp) {
    var lyr = comp.layer("AUDIO");
    if (lyr) return lyr;

    // Try audio_trimmed.wav
    try {
        lyr = comp.layer("audio_trimmed.wav");
        if (lyr) return lyr;
    } catch(e) {}

    // Find any audio layer
    for (var i = 1; i <= comp.numLayers; i++) {
        var L = comp.layer(i);
        if (L instanceof AVLayer && L.hasAudio) {
            try { L.name = "AUDIO"; } catch (_) {}
            return L;
        }
    }
    return null;
}

function autoResizeCoverInOutput(jobId) {
    var comp;
    try { comp = findCompByName("OUTPUT " + jobId); }
    catch(_) { return; }

    var cw = comp.width;
    var ch = comp.height;

    for (var i = 1; i <= comp.numLayers; i++) {
        var lyr = comp.layer(i);
        if (!(lyr instanceof AVLayer)) continue;

        var isCover = (lyr.name.toUpperCase() === "COVER") ||
                      (lyr.source && lyr.source.name.toUpperCase() === "COVER");
        if (!isCover) continue;

        var lw = lyr.source.width;
        var lh = lyr.source.height;
        if (!lw || !lh) continue;

        var scaleW = cw / lw;
        var scaleH = ch / lh;
        var scale = 100 * Math.max(scaleW, scaleH);

        try {
            lyr.property("Scale").setValue([scale, scale]);
            lyr.property("Position").setValue([cw / 2, ch / 2]);
        } catch(e) {}

        $.writeln("Auto-Fill scaled COVER in " + comp.name);
        return;
    }
}

function setWorkAreaToAudioDuration(jobId) {
    var comp;
    try { comp = findCompByName("LYRIC FONT " + jobId); }
    catch(_) { return; }

    var audio = ensureAudioLayer(comp);
    if (!audio || !audio.source || !audio.source.duration) {
        $.writeln("Could not get audio duration for LYRIC FONT " + jobId);
        return;
    }

    var dur = audio.source.duration;
    comp.duration = dur;
    comp.workAreaStart = 0;
    comp.workAreaDuration = dur;
    $.writeln("Set LYRIC FONT " + jobId + " duration to " + dur + "s");
}

function setOutputWorkAreaToAudio(jobId, audioPath) {
    // Import audio to get accurate duration
    var audioFile = new File(audioPath);
    if (!audioFile.exists) {
        $.writeln("Audio file not found for duration check: " + audioPath);
        return;
    }
    
    var imported = app.project.importFile(new ImportOptions(audioFile));
    var dur = imported.duration;
    imported.remove();
    
    $.writeln("Audio duration for job " + jobId + ": " + dur + "s");

    // Set OUTPUT comp duration
    try {
        var outputComp = findCompByName("OUTPUT " + jobId);
        outputComp.duration = dur;
        outputComp.workAreaStart = 0;
        outputComp.workAreaDuration = dur;
        $.writeln("Set OUTPUT " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set OUTPUT " + jobId + " duration: " + e.toString());
    }
    
    // Set LYRIC FONT comp duration
    try {
        var lyricComp = findCompByName("LYRIC FONT " + jobId);
        lyricComp.duration = dur;
        lyricComp.workAreaStart = 0;
        lyricComp.workAreaDuration = dur;
        $.writeln("Set LYRIC FONT " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set LYRIC FONT " + jobId + " duration: " + e.toString());
    }
    
    // Set BACKGROUND comp duration
    try {
        var bgComp = findCompByName("BACKGROUND " + jobId);
        bgComp.duration = dur;
        bgComp.workAreaStart = 0;
        bgComp.workAreaDuration = dur;
        $.writeln("Set BACKGROUND " + jobId + " duration to " + dur + "s");
    } catch(e) {
        $.writeln("Could not set BACKGROUND " + jobId + " duration: " + e.toString());
    }
}

function updateSongTitle(jobId, titleText) {
    if (!titleText) return;
    try {
        var assetsComp = findCompByName("Assets " + jobId);
        if (!assetsComp) return;

        var targetTextLayer = null;
        for (var i = 1; i <= assetsComp.numLayers; i++) {
            var lyr = assetsComp.layer(i);
            var txtProp = lyr.property("Source Text");
            if (txtProp) { targetTextLayer = lyr; break; }
        }

        if (!targetTextLayer) return;

        var txtProp = targetTextLayer.property("Source Text");
        var doc = txtProp.value;
        doc.text = String(titleText);
        txtProp.setValue(doc);

        $.writeln("Set song title for job " + jobId + ": " + titleText);
    } catch (e) {
        $.writeln("Could not update title for job " + jobId + ": " + e.toString());
    }
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

    if (!coverFootage) return;

    for (var L = 1; L <= assetComp.numLayers; L++) {
        var lyr = assetComp.layer(L);
        if (!(lyr instanceof AVLayer)) continue;
        if (!(lyr.source instanceof FootageItem)) continue;

        var srcName = (lyr.source.name || "").toLowerCase();
        var lyrName = (lyr.name || "").toLowerCase();

        var isCoverLayer =
            lyrName === "cover" ||
            lyrName.indexOf("album") !== -1 ||
            lyrName.indexOf("art") !== -1 ||
            srcName === "cover" ||
            srcName.indexOf("album") !== -1;

        if (!isCoverLayer) continue;

        try {
            lyr.replaceSource(coverFootage, false);
            $.writeln("Replaced album art layer in " + assetComp.name);
        } catch (e) {
            $.writeln("Could not replace layer: " + e.toString());
        }
    }
}

function addToRenderQueue(comp, jobFolder, jobId, songTitle, suffix) {
    try {
        // Normalize path
        jobFolder = String(jobFolder).replace(/\\/g, "/");
        
        // Get parent folder (jobs folder) and create renders directory
        var jobFolderObj = new Folder(jobFolder);
        var root = jobFolderObj.parent;
        
        var renderDir = new Folder(root.fsName + "/renders");
        if (!renderDir.exists) {
            renderDir.create();
        }

        var safeTitle = sanitizeFilename(songTitle);
        var filename = safeTitle + (suffix || "") + ".mp4";
        var outPath = renderDir.fsName.replace(/\\/g, "/") + "/" + filename;
        var outFile = new File(outPath);

        // Add to render queue
        var rq = app.project.renderQueue.items.add(comp);
        
        // Set output file (skip templates - use defaults)
        rq.outputModule(1).file = outFile;

        return outPath;
    } catch (err) {
        $.writeln("addToRenderQueue error: " + err.toString());
        return null;
    }
}

function sanitizeFilename(name) {
    if (!name) return "untitled";
    return String(name)
        .replace(/[\/\\:*?"<>|]/g, "")
        .replace(/\s+/g, " ")
        .replace(/^\s+|\s+$/g, "");
}

function clearAllJobComps() {
    $.writeln("Clearing all NOVA_JOB comps...");
    var count = 0;
    
    for (var i = app.project.numItems; i >= 1; i--) {
        var it = app.project.item(i);
        
        if (it instanceof CompItem && it.name.indexOf("NOVA_JOB_") === 0) {
            try {
                it.remove();
                count++;
            } catch (e) {}
        }
    }
    
    $.writeln("Deleted " + count + " old NOVA job comps");
}

// -----------------------------
// RUN
// -----------------------------
main();