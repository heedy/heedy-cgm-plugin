VERSION:=$(shell cat VERSION)
PLUGIN_NAME:=cgm

HEEDY:=$(shell test -f ./heedy && echo "./")heedy

.PHONY: clean clear watch debug release run


release: node_modules clear dist/cgm
	npm run build
	# Remove original files of pre-compressed content
	if test -d ./dist/cgm/public/static; then find ./dist/cgm/public/static -name "*.gz" -exec sh -c 'rm "$${0%.gz}"' {} ';';fi
	# Zip the plugin
	cd dist;zip -r heedy-cgm-plugin-${VERSION}.zip ./cgm

node_modules:
	if test -d frontend; then (cd frontend && npm i);fi
	npm i

dist/cgm:
	mkdir -p dist/cgm

testdb:
	$(HEEDY) create testdb --noserver --username=test --password=test
	mkdir testdb/plugins
	cd testdb/plugins; ln -s ../../dist/cgm cgm

debug: node_modules dist/cgm testdb
	npm run debug

watch: node_modules dist/cgm testdb
	npm run watch

run: testdb
	$(HEEDY) run testdb --verbose

clear:
	rm -rf dist

clean: clear
	rm -rf testdb
	if test -d node_modules; then rm -rf node_modules; fi
	if test -d frontend/node_modules; then rm -rf frontend/node_modules; fi

rename: clean
	find ./ -type f -exec sed -i -e 's/cgm/$(PLUGIN_NAME)/g' {} \;