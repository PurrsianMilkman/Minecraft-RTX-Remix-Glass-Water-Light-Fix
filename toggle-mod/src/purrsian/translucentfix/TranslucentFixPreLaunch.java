package purrsian.translucentfix;

import net.fabricmc.loader.api.entrypoint.PreLaunchEntrypoint;

/**
 * Runs before Minecraft and every other mod is loaded. The renderer mod reads
 * -Drtxremix.light.vanillaSnapshot exactly once, when ClientLightSnapshotPolicy loads, which happens during its own
 * initialisation, earlier than a normal mod entrypoint. Setting the property here is therefore the only place that
 * is early enough. With it true the mod never creates its ServerLightSnapshot, whose ColumnView throws
 * 'published light snapshot is read-only' on world join and leaves the integrated server's light task dead (chunks
 * stop loading, exit hangs on the saving screen). An explicit -D on the command line wins.
 */
public final class TranslucentFixPreLaunch implements PreLaunchEntrypoint {
    @Override
    public void onPreLaunch() {
        if (System.getProperty("rtxremix.light.vanillaSnapshot") == null) {
            System.setProperty("rtxremix.light.vanillaSnapshot", "true");
        }
    }
}
