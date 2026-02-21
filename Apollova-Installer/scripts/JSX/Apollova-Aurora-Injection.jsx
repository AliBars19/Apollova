// =====================================================
// APOLLOVA AURORA - After Effects Injection Script
// Injects job data into Aurora template compositions
// =====================================================

(function() {
    // Configuration - paths injected by GUI
    var JOBS_PATH = "{{JOBS_PATH}}";
    var TEMPLATE_PATH = "{{TEMPLATE_PATH}}";
    
    // Failsafe: If paths weren't injected, prompt user
    if (JOBS_PATH.indexOf("{{") === 0 || JOBS_PATH === "") {
        JOBS_PATH = promptForJobsFolder();
        if (!JOBS_PATH) {
            alert("Apollova Aurora: No jobs folder selected. Injection cancelled.");
            return;
        }
    }
    
    function promptForJobsFolder() {
        var folder = Folder.selectDialog("Select the Apollova-Aurora/jobs folder:");
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
                alert("Template file not found:\n" + TEMPLATE_PATH + "\n\nPlease open the Aurora template manually.");
                return;
            }
        }
        
        // Find job folders
        var jobsFolder = new Folder(JOBS_PATH);
        if (!jobsFolder.exists) {
            // Failsafe: prompt user
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
        
        // Sort by name
        jobFolders.sort(function(a, b) {
            return a.name.localeCompare(b.name);
        });
        
        var successCount = 0;
        var errorCount = 0;
        var errors = [];
        
        // Process each job
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
        
        // Report results
        var message = "Apollova Aurora Injection Complete!\n\n";
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
        var compName = "Aurora_" + padNumber(jobNumber, 3);
        var comp = findCompByName(compName);
        
        if (!comp) {
            // Try to duplicate template comp
            var templateComp = findCompByName("Aurora_Template") || findCompByName("Aurora_001");
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
                // Find AUDIO layer or add new one
                var audioLayer = findLayerByName(comp, "AUDIO");
                if (audioLayer) {
                    audioLayer.replaceSource(audioItem, false);
                } else {
                    audioLayer = comp.layers.add(audioItem);
                    audioLayer.name = "AUDIO";
                    audioLayer.moveToEnd();
                }
                
                // Adjust comp duration to match audio
                comp.duration = audioLayer.outPoint;
            }
        }
        
        // Import cover image
        if (jobData.cover_image) {
            var coverFile = new File(jobData.cover_image);
            if (coverFile.exists) {
                var coverItem = importFile(coverFile);
                if (coverItem) {
                    var coverLayer = findLayerByName(comp, "COVER") || findLayerByName(comp, "cover");
                    if (coverLayer) {
                        coverLayer.replaceSource(coverItem, false);
                    }
                }
            }
        }
        
        // Read lyrics
        var lyricsFile = new File(jobData.lyrics_file);
        if (lyricsFile.exists) {
            lyricsFile.open("r");
            var lyricsContent = lyricsFile.read();
            lyricsFile.close();
            
            var lyrics = JSON.parse(lyricsContent);
            
            // Add markers to AUDIO layer
            var audioLayer = findLayerByName(comp, "AUDIO");
            if (audioLayer && lyrics.length > 0) {
                // Clear existing markers
                while (audioLayer.marker.numKeys > 0) {
                    audioLayer.marker.removeKey(1);
                }
                
                // Add new markers
                for (var j = 0; j < lyrics.length; j++) {
                    var seg = lyrics[j];
                    var markerValue = new MarkerValue(seg.lyric_current || seg.text || "");
                    markerValue.comment = JSON.stringify(seg);
                    audioLayer.marker.setValueAtTime(seg.t || seg.time || 0, markerValue);
                }
            }
        }
        
        // Set colors (if color layers exist)
        if (jobData.colors && jobData.colors.length >= 2) {
            setLayerColor(comp, "COLOR_1", jobData.colors[0]);
            setLayerColor(comp, "COLOR_2", jobData.colors[1]);
            setLayerColor(comp, "BG_COLOR", jobData.colors[0]);
        }
        
        // Set song title text (if text layer exists)
        var titleLayer = findLayerByName(comp, "SONG_TITLE") || findLayerByName(comp, "TITLE");
        if (titleLayer && titleLayer.property("Source Text")) {
            titleLayer.property("Source Text").setValue(jobData.song_title || "");
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
    
    function hexToRGB(hex) {
        hex = hex.replace("#", "");
        var r = parseInt(hex.substring(0, 2), 16) / 255;
        var g = parseInt(hex.substring(2, 4), 16) / 255;
        var b = parseInt(hex.substring(4, 6), 16) / 255;
        return [r, g, b, 1];
    }
    
    function setLayerColor(comp, layerName, hexColor) {
        var layer = findLayerByName(comp, layerName);
        if (layer) {
            var effects = layer.property("Effects");
            if (effects) {
                var fill = effects.property("Fill");
                if (fill) {
                    fill.property("Color").setValue(hexToRGB(hexColor));
                }
            }
        }
    }
    
    // JSON polyfill for older ExtendScript
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
    
    // Run main
    main();
})();
