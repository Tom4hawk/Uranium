#Creates the Pirate translation files.

import sys #To get command line arguments.

pot_file = sys.argv[1]
po_file = sys.argv[2]

#Translates English to Pirate.
def translate(english):
    import pirateofdoom
    result = []
    for word in english.split(" "):
        if word in pirateofdoom.pirate:
            result.append(pirateofdoom.pirate[word])
        else:
            print("Untranslated word: {word}".format(word = word))
            result.append(word)
    return " ".join(result)

translations = {}

last_id = ""
last_id_plural = ""
last_ctxt = ""
last_str = ""
state = "unknown"
with open(pot_file) as f:
    for line in f:
        if line.startswith("msgctxt"):
            state = "ctxt"
            if last_id != "":
                translations[(last_ctxt, last_id, last_id_plural)] = last_str
            last_ctxt = ""
            last_id = ""
            last_id_plural = ""
            last_str = ""
        elif line.startswith("msgid_plural"):
            state = "idplural"
        elif line.startswith("msgid"):
            state = "id"
        elif line.startswith("msgstr"):
            state = "str"

        if line.count('"') >= 2: #There's an ID on this line!
            line = line[line.find('"') + 1:] #Strip everything before the first ".
            line = line[:line.rfind('"')] #And after the last ".

            if state == "ctxt":
                last_ctxt += line #What's left is the context.
            elif state == "idplural":
                last_id_plural += line #Or the plural ID.
            elif state == "id":
                last_id += line #Or the ID.
            elif state == "str":
                last_str += line #Or the actual string.

import pirateofdoom #The translation dictionary.
for key, _ in translations.items():
    context, english, english_plural = key
    pirate = translate(english)
    pirate_plural = translate(english_plural)
    translations[key] = (pirate, pirate_plural)

with open(po_file, "w") as f:
    f.write("""msgid ""
msgstr ""
"Project-Id-Version: Pirate\\n"
"Report-Msgid-Bugs-To: r.dulek@ultimaker.com\\n"
"POT-Creation-Date: 1492\\n"
"PO-Revision-Date: 1492\\n"
"Last-Translator: Ghostkeeper and Awhiemstra\\n"
"Language-Team: Ghostkeeper and Awhiemstra\\n"
"Language: Pirate\\n"
"Lang-Code: en\\n"
"Country-Code: 7S\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"
""")
    for key, value in translations.items():
        context, english, english_plural = key
        pirate, pirate_plural = value
        f.write('msgctxt "{context}"\n'.format(context = context))
        if english_plural == "": #No plurals in this item.
            f.write('msgid "{english}"\n'.format(english = english))
            f.write('msgstr "{pirate}"\n'.format(pirate = pirate))
        else:
            f.write('msgid "{english}"\n'.format(english = english))
            f.write('msgid_plural "{english_plural}"\n'.format(english_plural = english_plural))
            f.write('msgstr[0] "{pirate}"\n'.format(pirate = pirate))
            f.write('msgstr[1] "{pirate_plural}"\n'.format(pirate_plural = pirate_plural))
        f.write("\n") #Empty line.