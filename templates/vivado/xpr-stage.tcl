namespace eval buildsys {}
set ::buildsys::xpr $(xpr)
set ::buildsys::stage $(stage)
set ::buildsys::synthesis_run $(synthesis_run)
set ::buildsys::implementation_run $(implementation_run)
set ::buildsys::fileset $(fileset)
set ::buildsys::hw_server $(hw_server)
set ::buildsys::device_pattern $(device_pattern)
set ::buildsys::bitstream_hint $(bitstream_hint)

# All phases run within the existing project and retain their native outputs.
namespace eval buildsys {
    variable project_open 0
    variable simulation_open 0
    variable manager_open 0
    variable manager_close close_hw_manager
    variable server_open 0
    variable target_open 0
}

proc buildsys::run_object {name} {
    set objects [get_runs -quiet $name]
    if {[llength $objects] != 1} {
        error "Expected Vivado run '$name' in the exported project; re-export the XPR if its runs were removed"
    }
    return [lindex $objects 0]
}

proc buildsys::run_valid {name phase} {
    set object [run_object $name]
    set status [get_property STATUS $object]
    set progress [string trimright [get_property PROGRESS $object] %]
    set refresh [get_property NEEDS_REFRESH $object]
    if {![string is boolean -strict $refresh] || $refresh} { return 0 }
    if {![string is double -strict $progress] || $progress < 100} { return 0 }
    switch -- $phase {
        synthesis { return [string equal -nocase $status "synth_design Complete!"] }
        implementation { return [regexp -nocase {^(route_design|write_bitstream) Complete!$} $status] }
        bitstream { return [string equal -nocase $status "write_bitstream Complete!"] }
        default { error "Unknown run phase '$phase'" }
    }
}

proc buildsys::ensure_run {name phase} {
    set missing_bitstream 0
    if {[run_valid $name $phase]} {
        if {$phase ne "bitstream" || [find_bitstream] ne ""} {
            puts "Reusing completed Vivado run $name ($phase)"
            return
        }
        set missing_bitstream 1
    }
    # Extend a routed implementation to write_bitstream without rerouting.
    # Failed, stale, and incomplete runs start again from a clean run state.
    if {$missing_bitstream || $phase ne "bitstream" || ![run_valid $name implementation]} {
        reset_run $name
    }
    if {$phase eq "bitstream"} {
        launch_runs $name -to_step write_bitstream
    } else {
        launch_runs $name
    }
    wait_on_run $name
    if {![run_valid $name $phase]} {
        error "Vivado run '$name' did not complete $phase successfully: [get_property STATUS [run_object $name]]"
    }
}

proc buildsys::find_bitstream {} {
    variable implementation_run
    set object [run_object $implementation_run]
    foreach property {PROGRAM.FILE BITSTREAM.FILE} {
        # These properties are absent on runs in Vivado 2018.3.
        if {[lsearch -exact [list_property $object] $property] < 0} { continue }
        set candidate [get_property $property $object]
        if {$candidate ne "" && [file isfile $candidate]} {
            return [file normalize $candidate]
        }
    }
    set directory [get_property DIRECTORY $object]
    if {$directory ne "" && [file isdirectory $directory]} {
        set candidates [lsort [glob -nocomplain -directory $directory *.bit]]
        # Prefer the active design top when several files remain in a run dir.
        set top [get_property TOP [get_filesets sources_1]]
        set preferred [file join $directory "${top}.bit"]
        if {[file isfile $preferred]} { return [file normalize $preferred] }
        foreach candidate $candidates {
            if {[file isfile $candidate]} { return [file normalize $candidate] }
        }
    }
    return ""
}

proc buildsys::existing_bitstream {} {
    variable synthesis_run
    variable implementation_run
    variable bitstream_hint
    if {![run_valid $synthesis_run synthesis] || ![run_valid $implementation_run bitstream]} {
        error "No valid bitstream in this XPR; $bitstream_hint"
    }
    set bitstream [find_bitstream]
    if {$bitstream eq ""} { error "Bitstream file is missing; $bitstream_hint" }
    return $bitstream
}

proc buildsys::simulate {} {
    variable fileset
    variable simulation_open
    set objects [get_filesets -quiet $fileset]
    if {[llength $objects] != 1} {
        error "Simulation fileset '$fileset' is missing from this XPR; explicitly re-export the project"
    }
    set object [lindex $objects 0]
    # Vivado 2018.3 supports behavioral, post-synthesis, post-implementation;
    # 'batch' is a Vivado process mode, not a launch_simulation mode.
    set_property xsim.simulate.runtime all $object
    set_property xsim.simulate.log_all_signals true $object
    set simulation_open 1
    launch_simulation -mode behavioral -simset $object
    close_sim
    set simulation_open 0
}

proc buildsys::program {bitstream} {
    variable hw_server
    variable device_pattern
    variable manager_open
    variable manager_close
    variable server_open
    variable target_open
    # The order is deliberate: no hardware connection until bitstream validation.
    if {[catch {open_hw_manager} message options]} {
        # Vivado 2018.3 exposes Hardware Manager as open_hw/close_hw.
        if {$message ne {invalid command name "open_hw_manager"}} {
            return -options $options $message
        }
        open_hw
        set manager_close close_hw
    }
    set manager_open 1
    if {[catch {connect_hw_server -url $hw_server} message]} {
        error "Cannot connect to Vivado Hardware Server '$hw_server': $message"
    }
    set server_open 1
    if {[catch {open_hw_target} message]} {
        error "Cannot open FPGA hardware target (is a board connected?): $message"
    }
    set target_open 1
    if {[catch {get_hw_devices -quiet} devices]} {
        error "Cannot enumerate FPGA hardware devices on '$hw_server': $devices"
    }
    if {[llength $devices] == 0} { error "No FPGA hardware devices found on '$hw_server'" }
    set selected ""
    foreach device $devices {
        set name [get_property NAME $device]
        if {[string match $device_pattern $name]} {
            set selected $device
            break
        }
    }
    if {$selected eq ""} { error "No hardware device matches name glob '$device_pattern'" }
    current_hw_device $selected
    set_property PROGRAM.FILE $bitstream $selected
    if {[catch {program_hw_devices $selected} message]} {
        error "Programming FPGA device '$selected' failed: $message"
    }
    refresh_hw_device $selected
}

proc buildsys::perform {} {
    variable stage
    variable synthesis_run
    variable implementation_run
    switch -- $stage {
        simulation { simulate }
        synthesis { ensure_run $synthesis_run synthesis }
        implementation {
            ensure_run $synthesis_run synthesis
            ensure_run $implementation_run implementation
        }
        bitstream {
            ensure_run $synthesis_run synthesis
            ensure_run $implementation_run implementation
            ensure_run $implementation_run bitstream
            set bitstream [existing_bitstream]
            puts "BUILDSYS_BITSTREAM $bitstream"
        }
        program {
            set bitstream [existing_bitstream]
            puts "BUILDSYS_BITSTREAM $bitstream"
            program $bitstream
        }
        default { error "Unknown XPR stage '$stage'" }
    }
}

proc buildsys::cleanup {} {
    # Attempt all cleanup steps even if one fails, while preserving the error.
    set failures {}
    variable manager_close
    foreach {flag command} {
        simulation_open close_sim
        target_open close_hw_target
        server_open disconnect_hw_server
        manager_open close_hw_manager
        project_open close_project
    } {
        variable $flag
        if {[set $flag]} {
            if {$flag eq "manager_open"} { set command $manager_close }
            if {[catch {uplevel #0 $command} message]} { lappend failures $message }
            set $flag 0
        }
    }
    if {[llength $failures]} { error [join $failures "; "] }
}

set buildsys_status [catch {
    open_project $::buildsys::xpr
    set ::buildsys::project_open 1
    buildsys::perform
} buildsys_error buildsys_options]
set buildsys_cleanup_status [catch {buildsys::cleanup} buildsys_cleanup_error]
if {$buildsys_status || $buildsys_cleanup_status} {
    if {$buildsys_status} {
        puts stderr "ERROR: $buildsys_error"
        puts stderr [dict get $buildsys_options -errorinfo]
    }
    if {$buildsys_cleanup_status} { puts stderr "ERROR: Cleanup failed: $buildsys_cleanup_error" }
    exit 1
}
puts "BUILDSYS_XPR_COMPLETE"
exit 0
