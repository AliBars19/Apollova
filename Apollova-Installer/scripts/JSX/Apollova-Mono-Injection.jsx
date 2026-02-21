// =====================================================
// APOLLOVA MONO - After Effects Injection Script
// Injects job data into Mono template compositions
// Word-by-word lyrics, black/white alternating
// =====================================================

(function() {
    // Configuration - paths injected by GUI
    var JOBS_PATH = "{{JOBS_PATH}}";
    var TEMPLATE_PATH = "{{TEMPLATE_PATH}}";
    
    // Failsafe: If paths weren't injected, prompt user
    if (JOBS_PATH.indexOf("{{") === 0 || JOBS_PATH === "") {
        JOBS_PATH = promptForJobsFolder();
        if (!JOBS_PATH) {
            alert("Apollova Mono: No jobs folder selected. Injection cancelled.");
            return;
        }
    }
    
    function promptForJobsFolder() {
        var folder = Folder.selectDialog("Select the Apollova-Mono/jobs folder:");
        if (folder) {
            return folder.fsName.replace(/\\/g, "/");
        }
        return null;
    }
    
    function main() {
        // Check if we need to open the template
        if (app.project.file === null) {
            var templateFile = new File(TEMPLATE_PATH);
            if (templateFile.exists) {
                app.open(templateFile);
            } else {
                alert("Template file not found:\n" + TEMPLATE_PATH + "\n\nPlease open the Mono template manually.");
                return;
            }
        }
        
        // Find job folders
        var jobsFolder = new Folder(JOBS_PATH);
        if (!jobsFolder.exists) {
            var result = confirm("Jobs folder not found at:\n" + JOBS_PATH + "\n\nWould you like to select it manually?");
            if (result) {
                JOBS_PATH = promptForJobsFolder();
                if (!JOBS_PATH) {
                    alert("No folder selected. Please contact support at apollova.co.uk");
                    return;
                }
                jobsFolder = new Folder(JOBS_PATH);
            } else {
                alert("Injection cancelled. Please contact support at apollova.co.uk if this issue persists.");
                return;
            }
        }
        
        // Get all job_XXX folders
        var jobFolders = jobsFolder.getFiles(function(f) {
            return f instanceof Folder && f.name.match(/^job_\d+$/);
        });
        
        if (jobFolders.length === 0) {
            alert("No job folders found in:\n" + JOBS_PATH + "\n\nPlease create jobs first using the Apollova GUI.");
            return;
        }
        
        jobFolders.sort(function(a, b) {
            return a.name.localeCompare(b.name);
        });
        
        var successCount = 0;
        var errorCount = 0;
        var errors = [];
        
        for (var i = 0; i < jobFolders.length; i++) {
            try {
                var result = processJob(jobFolders[i], i + 1);
                if (result) {
                    successCount++;
                } else {
                    errorCount++;
                }
            } catch (e) {
                errorCount++;
                errors.push("Job " + (i + 1) + ": " + e.toString());
            }
        }
        
        var message = "Apollova Mono Injection Complete!\n\n";
        message += "✓ Successfully processed: " + successCount + " jobs\n";
        if (errorCount > 0) {
            message += "✗ Errors: " + errorCount + " jobs\n\n";
            message += errors.slice(0, 5).join("\n");
        }
        message += "\n\nNext: Review compositions and add to render queue.";
        
        alert(message);
    }
    
    function processJob(jobFolder, jobNumber) {
        // Read job_data.json
        var dataFile = new File(jobFolder.fsName + "/job_data.json");
        if (!dataFile.exists) {
            throw new Error("job_data.json not found");
        }
        
        dataFile.open("r");
        var jsonContent = dataFile.read();
        dataFile.close();
        
        var jobData = JSON.parse(jsonContent);
        
        // Find or create composition
        var compName = "Mono_" + padNumber(jobNumber, 3);
        var comp = findCompByName(compName);
        
        if (!comp) {
            var templateComp = findCompByName("Mono_Template") || findCompByName("Mono_001");
            if (templateComp) {
                comp = templateComp.duplicate();
                comp.name = compName;
            } else {
                throw new Error("Template composition not found");
            }
        }
        
        // Import audio
        var audioFile = new File(jobData.audio_trimmed);
        if (audioFile.exists) {
            var audioItem = importFile(audioFile);
            if (audioItem) {
                var audioLayer = findLayerByName(comp, "AUDIO");
                if (audioLayer) {
                    audioLayer.replaceSource(audioItem, false);
                } else {
                    audioLayer = comp.layers.add(audioItem);
                    audioLayer.name = "AUDIO";
                    audioLayer.moveToEnd();
                }
                comp.duration = audioLayer.outPoint;
            }
        }
        
        // Read lyrics and create markers with word timing
        var lyricsFile = new File(jobData.lyrics_file);
        if (lyricsFile.exists) {
            lyricsFile.open("r");
            var lyricsContent = lyricsFile.read();
            lyricsFile.close();
            
            var lyrics = JSON.parse(lyricsContent);
            
            var audioLayer = findLayerByName(comp, "AUDIO");
            if (audioLayer && lyrics.length > 0) {
                // Clear existing markers
                while (audioLayer.marker.numKeys > 0) {
                    audioLayer.marker.removeKey(1);
                }
                
                // Add markers with word timing and color info
                for (var j = 0; j < lyrics.length; j++) {
                    var seg = lyrics[j];
                    var text = seg.lyric_current || seg.text || "";
                    
                    // Create marker data with word timing if available
                    var markerData = {
                        text: text,
                        words: seg.words || [],
                        color: (j % 2 === 0) ? "white" : "black",
                        index: j,
                        end_time: seg.end_time || (lyrics[j + 1] ? lyrics[j + 1].t || lyrics[j + 1].time : comp.duration)
                    };
                    
                    var markerValue = new MarkerValue(text);
                    markerValue.comment = JSON.stringify(markerData);
                    
                    var time = seg.t || seg.time || 0;
                    audioLayer.marker.setValueAtTime(time, markerValue);
                }
            }
        }
        
        return true;
    }
    
    // Helper functions
    function padNumber(num, size) {
        var s = "000" + num;
        return s.substr(s.length - size);
    }
    
    function findCompByName(name) {
        for (var i = 1; i <= app.project.numItems; i++) {
            var item = app.project.item(i);
            if (item instanceof CompItem && item.name === name) {
                return item;
            }
        }
        return null;
    }
    
    function findLayerByName(comp, name) {
        for (var i = 1; i <= comp.numLayers; i++) {
            if (comp.layer(i).name.toUpperCase() === name.toUpperCase()) {
                return comp.layer(i);
            }
        }
        return null;
    }
    
    function importFile(file) {
        try {
            var importOptions = new ImportOptions(file);
            return app.project.importFile(importOptions);
        } catch (e) {
            return null;
        }
    }
    
    // JSON polyfill
    if (typeof JSON === "undefined") {
        JSON = {
            parse: function(str) {
                return eval("(" + str + ")");
            },
            stringify: function(obj) {
                if (obj === null) return "null";
                if (typeof obj === "undefined") return undefined;
                if (typeof obj === "number" || typeof obj === "boolean") return String(obj);
                if (typeof obj === "string") return '"' + obj.replace(/"/g, '\\"') + '"';
                if (obj instanceof Array) {
                    var arr = [];
                    for (var i = 0; i < obj.length; i++) {
                        arr.push(JSON.stringify(obj[i]));
                    }
                    return "[" + arr.join(",") + "]";
                }
                if (typeof obj === "object") {
                    var props = [];
                    for (var key in obj) {
                        if (obj.hasOwnProperty(key)) {
                            props.push('"' + key + '":' + JSON.stringify(obj[key]));
                        }
                    }
                    return "{" + props.join(",") + "}";
                }
                return String(obj);
            }
        };
    }
    
    main();
})();
